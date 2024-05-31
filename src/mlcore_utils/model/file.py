import os
from typing import Optional
import io
import tarfile
import glob
from result import Result, Ok, Err
from tarfile import TarFile
from attrs import define, field
from result import Result


@define
class Tarball(object):
    source_directory: str = field()
    name: str = field()
    destination_directory: str = field(default="/tmp")

    def create(self) -> Result[TarFile, str]:
        return Tarball.tar_zip_a_folder(
            self.source_directory, self.name, self.destination_directory
        )

    @classmethod
    def tar_zip_a_folder(
        cls, source_dir: str, tarball_name: str, parent_directory: str = "/tmp"
    ) -> Result[TarFile, str]:
        try:
            tarball_path = os.path.join(parent_directory, f"{tarball_name}.tar.gz")
            if os.path.exists(tarball_path):
                os.remove(tarball_path)
            tar = tarfile.open(tarball_path, "w:gz")
            for file_name in glob.glob(os.path.join(source_dir, "*")):
                tar.add(file_name, os.path.basename(file_name))
            tar.close()
            return Ok(tar)
        except Exception as e:
            return Err("tarball creation failed with error " + str(e))


class Generator_To_FileLike(io.BytesIO):

    def __init__(self, iter):
        self._iter = iter
        self._left = ""

    def readable(self):
        return True

    def _read1(self, n=None):
        while not self._left:
            try:
                self._left = next(self._iter)
            except StopIteration:
                break
        ret = self._left[:n]
        self._left = self._left[len(ret) :]
        return ret

    def read(self, n=None):
        l = []
        if n is None or n < 0:
            while True:
                m = self._read1()
                if not m:
                    break
                l.append(m)
        else:
            while n > 0:
                m = self._read1(n)
                if not m:
                    break
                n -= len(m)
                l.append(m)
        return bytes("".join(l), "utf-8")

    def readline(self, size: Optional[int] = None):
        l = []
        while True:
            i = self._left.find("\n")
            if i == -1:
                l.append(self._left)
                try:
                    self._left = next(self._iter)
                except StopIteration:
                    self._left = ""
                    break
            else:
                l.append(self._left[: i + 1])
                self._left = self._left[i + 1 :]
                break
        return bytes("".join(l), "utf-8")
