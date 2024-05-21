from fuse import FUSE, FuseOSError, Operations
import chdimage
import errno
import fnmatch
import logging
import os
import re
import sys

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

        head, tail = os.path.split(root)
        basename, ext = os.path.splitext(tail)
        #logging.basicConfig(level=logging.DEBUG)
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
        logging.info(self.tracks)

    def getattr(self, path, fh=None):
        logging.info(f'getattr: {path} - {fh}')

        head, tail = os.path.split(path)
        if head == '/':
            if self.cue_sheet_file_name == tail:
                return self.default_file_attrs | {'st_size': len(self.cue_sheet)}
            elif track := self.tracks.get(tail):
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

    def readdir(self, path, fh):
        logging.info(f'readdir: {path} - {fh}')

        head, tail = os.path.split(path)
        if head == '/':
            for r in list(self.tracks.keys()) + ['.', '..', self.cue_sheet_file_name]:
                if tail == '' or fnmatch.fnmatch(r, tail):
                    yield r

    def open(self, path, flags):
        logging.info(f'open: {path} - {flags}')

        head, tail = os.path.split(path)
        if head == '/':
            if self.tracks.get(tail) is not None:
                if flags & 0o100000:
                    return 0
                else:
                    return -errno.EACCES
            else:
                return -errno.ENOENT

    def read(self, path, size, offset, fh):
        logging.info(f'read: {path} - {size} - {offset} - {fh}')

        head, tail = os.path.split(path)
        if head == '/':
            if self.cue_sheet_file_name == tail:
                return self.cue_sheet[offset:offset+size]
            elif track := self.tracks.get(tail):
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
