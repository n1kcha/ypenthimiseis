# PyInstaller hook για το curl_cffi (εναλλακτική σύνδεση HTTP/3 / TLS σαν του Chrome).
# Τα Windows wheels είναι φτιαγμένα με delvewheel: το libcurl-impersonate-*.dll βρίσκεται
# στον φάκελο curl_cffi.libs δίπλα στο πακέτο και πρέπει να μπει κι αυτός στο exe.
from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_delvewheel_libs_directory,
    collect_submodules,
)

hiddenimports = collect_submodules("curl_cffi", filter=lambda name: ".cli" not in name)
hiddenimports += ["_cffi_backend", "certifi"]
datas = collect_data_files("curl_cffi")
binaries = []
datas, binaries = collect_delvewheel_libs_directory("curl_cffi", datas=datas, binaries=binaries)
