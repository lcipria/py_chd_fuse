from fuse import FUSE, FuseOSError, Operations
from pathlib import Path
import chdimage
import errno
import logging
import os
import sys
import re

class CHDFS(Operations):
    @property
    def default_file_attrs(self):
        return {
            'st_atime': 0,
            'st_ctime': 0,
            'st_mtime': 0,
            'st_mode': 0o100444,
            'st_nlink': 1,
            'st_uid': 0,
            'st_gid': 0,
            }

    def __init__(self, root):

        basename = Path(root).stem
        self.chd = chdimage.open(root)
        self.tracks = {}
        self.cue_sheet = ''
        self.cue_sheet_file_name = f'{basename}.cue'
        for track_n in range(1, self.chd.num_tracks()+1):
            event = None
            lba = self.chd.current_global_msf().to_lba()
            size = 0
            track_file_name = f'{basename} (Track {str(track_n).zfill(len(str(self.chd.num_tracks())))}).bin'
            track_mode = str(self.chd.current_track_type()) # AUDIO | MODE1_RAW | MODE1 | MODE2_RAW | MODE2_FORM1 | MODE2_FORM2 | MODE2_FORM_MIX
            track_mode = re.sub('(?<=MODE[0-9]).+', '/2352', track_mode) # AUDIO | MODE1/2352 | MODE2/2352

            while event != chdimage.Event.TRACKCHANGE and event != chdimage.Event.ENDOFDISC:
                size += len(self.chd.copy_current_sector())
                event = self.chd.advance_position()

            self.cue_sheet += f'FILE {repr(track_file_name)} BINARY\n  TRACK {str(track_n).zfill(2)} {track_mode}\n    INDEX 01 00:00:00\n'

            self.tracks[track_file_name] = {
                'track_n': track_n,
                'lba': lba,
                'attr': self.default_file_attrs | {'st_size': size},
                }
        self.cue_sheet = self.cue_sheet.encode() # serve per leggerlo come file
        print(self.tracks)

    def getattr(self, path, fh=None):
        print(f'getattr: {path} - {fh}')

        if self.cue_sheet_file_name == Path(path).name:
            return self.default_file_attrs | {'st_size': len(self.cue_sheet)}
        elif track := self.tracks.get(Path(path).name):
            return track['attr']
        else:
            return {
                'st_atime': 0,
                'st_ctime': 0,
                'st_mtime': 0,
                'st_mode': 0o40555,
                'st_nlink': 1,
                'st_size': 4096,
                'st_uid': 0,
                'st_gid': 0,
                }

    def readdir(self, path, fh): # dumb as shit, it return always all content
        print(f'readdir: {path} - {fh}')
        for r in self.tracks.keys():
            yield r
        for r in ['.', '..', self.cue_sheet_file_name]:
            yield r

    def open(self, path, flags):
        print(f'open: {path} - {flags}')
        if self.tracks.get(Path(path).name) is not None:
            if flags & 0o100000:
                return 0
            else:
                return -errno.EACCES
        else:
            return -errno.ENOENT

    def read(self, path, size, offset, fh):
        print(f'read: {path} - {size} - {offset} - {fh}')

        if self.cue_sheet_file_name == Path(path).name:
            return self.cue_sheet[offset:offset+size]
        elif track := self.tracks.get(Path(path).name):
            self.chd.set_location(chdimage.MsfIndex.from_lba(track['lba'] + int(offset / 2352)))
            seek = offset % 2352
            buffer = self.chd.copy_current_sector()[seek:]
            event = self.chd.advance_position()

            while len(buffer) < size and event != chdimage.Event.TRACKCHANGE and event != chdimage.Event.ENDOFDISC:
                buffer += self.chd.copy_current_sector()
                event = self.chd.advance_position()

            return buffer[:size]
        else:
            return -errno.ENOENT

def main(mountpoint, root):
    FUSE(CHDFS(root), mountpoint, nothreads=True, foreground=True)

if __name__ == '__main__':
    main(sys.argv[2], sys.argv[1])
