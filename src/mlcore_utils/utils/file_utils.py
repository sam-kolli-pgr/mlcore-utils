import os
import glob
import tarfile
from result import Result, Ok, Err


def tar_zip_a_folder(
    source_dir: str, tarball_name: str, tarfile_path: str = "/tmp"
) -> Result[tarfile.TarFile, str]:
    try:
        tarball_path = os.path.join(tarfile_path, f"{tarball_name}.tar.gz")
        if os.path.exists(tarball_path):
            os.remove(tarball_path)
        tar = tarfile.open(tarball_path, "w:gz")
        for file_name in glob.glob(os.path.join(source_dir, "*")):
            tar.add(file_name, os.path.basename(file_name))
        tar.close()
        return Ok(tar)
    except Exception as e:
        return Err("tarball creation failed with error " + str(e))
