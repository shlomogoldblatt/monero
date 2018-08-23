#!/usr/bin/env python3
# Converts Google's protobuf python definitions of TREZOR wire messages
# to plain-python objects as used in TREZOR Core and python-trezor

import argparse
import logging
import os
import re
import shutil
import subprocess
import sys
import glob
import tempfile
import hashlib


AUTO_HEADER = "# Automatically generated by pb2cpp\n"

# Fixing GCC7 compilation error
UNDEF_STATEMENT = """
#ifdef minor
#undef minor
#endif
"""


def which(pgm):
    path = os.getenv('PATH')
    for p in path.split(os.path.pathsep):
        p = os.path.join(p, pgm)
        if os.path.exists(p) and os.access(p, os.X_OK):
            return p


PROTOC = which("protoc")
if not PROTOC:
    print("protoc command not found")
    sys.exit(1)

PROTOC_PREFIX = os.path.dirname(os.path.dirname(PROTOC))
PROTOC_INCLUDE = os.path.join(PROTOC_PREFIX, "include")


def namespace_file(fpath, package):
    """Adds / replaces package name. Simple regex parsing, may use https://github.com/ph4r05/plyprotobuf later"""
    with open(fpath) as fh:
        fdata = fh.read()

    re_syntax = re.compile(r"^syntax\s*=")
    re_package = re.compile(r"^package\s+([^;]+?)\s*;\s*$")
    lines = fdata.split("\n")

    line_syntax = None
    line_package = None
    for idx, line in enumerate(lines):
        if line_syntax is None and re_syntax.match(line):
            line_syntax = idx
        if line_package is None and re_package.match(line):
            line_package = idx

    if package is None:
        if line_package is None:
            return
        else:
            lines.pop(line_package)

    else:
        new_package = "package %s;" % package
        if line_package is None:
            lines.insert(line_syntax + 1 if line_syntax is not None else 0, new_package)
        else:
            lines[line_package] = new_package

    new_fdat = "\n".join(lines)
    with open(fpath, "w+") as fh:
        fh.write(new_fdat)
    return new_fdat


def protoc(files, out_dir, additional_includes=(), package=None, force=False):
    """Compile code with protoc and return the data."""

    include_dirs = set()
    include_dirs.add(PROTOC_INCLUDE)
    include_dirs.update(additional_includes)

    with tempfile.TemporaryDirectory() as tmpdir_protob, tempfile.TemporaryDirectory() as tmpdir_out:
        include_dirs.add(tmpdir_protob)

        new_files = []
        for file in files:
            bname = os.path.basename(file)
            tmp_file = os.path.join(tmpdir_protob, bname)

            shutil.copy(file, tmp_file)
            if package is not None:
                namespace_file(tmp_file, package)
            new_files.append(tmp_file)

        protoc_includes = ["-I" + dir for dir in include_dirs if dir]

        exec_args = (
            [
                PROTOC,
                "--cpp_out",
                tmpdir_out,
            ]
            + protoc_includes
            + new_files
        )

        subprocess.check_call(exec_args)

        # Fixing gcc compilation and clashes with "minor" field name
        add_undef(tmpdir_out)

        # Scan output dir, check file differences
        update_message_files(tmpdir_out, out_dir, force)


def update_message_files(tmpdir_out, out_dir, force=False):
    files = glob.glob(os.path.join(tmpdir_out, '*.pb.*'))
    for fname in files:
        bname = os.path.basename(fname)
        dest_file = os.path.join(out_dir, bname)
        if not force and os.path.exists(dest_file):
            data = open(fname, 'rb').read()
            data_hash = hashlib.sha3_256(data).digest()
            data_dest = open(dest_file, 'rb').read()
            data_dest_hash = hashlib.sha3_256(data_dest).digest()
            if data_hash == data_dest_hash:
                continue

        shutil.copy(fname, dest_file)


def add_undef(out_dir):
    files = glob.glob(os.path.join(out_dir, '*.pb.*'))
    for fname in files:
        with open(fname) as fh:
            lines = fh.readlines()

        idx_insertion = None
        for idx in range(len(lines)):
            if '@@protoc_insertion_point(includes)' in lines[idx]:
                idx_insertion = idx
                break

        if idx_insertion is None:
            pass

        lines.insert(idx_insertion + 1, UNDEF_STATEMENT)
        with open(fname, 'w') as fh:
            fh.write("".join(lines))


def strip_leader(s, prefix):
    """Remove given prefix from underscored name."""
    leader = prefix + "_"
    if s.startswith(leader):
        return s[len(leader) :]
    else:
        return s


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    parser = argparse.ArgumentParser()
    # fmt: off
    parser.add_argument("proto", nargs="+", help="Protobuf definition files")
    parser.add_argument("-o", "--out-dir", help="Directory for generated source code")
    parser.add_argument("-n", "--namespace", default=None, help="Message namespace")
    parser.add_argument("-I", "--protoc-include", action="append", help="protoc include path")
    parser.add_argument("-P", "--protobuf-module", default="protobuf", help="Name of protobuf module")
    parser.add_argument("-f", "--force", default=False, help="Overwrite existing files")
    # fmt: on
    args = parser.parse_args()

    protoc_includes = args.protoc_include or (os.environ.get("PROTOC_INCLUDE"),)

    protoc(
        args.proto, args.out_dir, protoc_includes, package=args.namespace, force=args.force
    )


