#!/usr/bin/python
# -*- coding: utf-8 -*- 

#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
#    Dieses Programm ist Freie Software: Sie können es unter den Bedingungen
#    der GNU General Public License, wie von der Free Software Foundation,
#    Version 3 der Lizenz oder (nach Ihrer Wahl) jeder neueren
#    veröffentlichten Version, weiterverbreiten und/oder modifizieren.
#
#    Dieses Programm wird in der Hoffnung, dass es nützlich sein wird, aber
#    OHNE JEDE GEWÄHRLEISTUNG, bereitgestellt; sogar ohne die implizite
#    Gewährleistung der MARKTFÄHIGKEIT oder EIGNUNG FÜR EINEN BESTIMMTEN ZWECK.
#    Siehe die GNU General Public License für weitere Details.
#
#    Sie sollten eine Kopie der GNU General Public License zusammen mit diesem
#    Programm erhalten haben. Wenn nicht, siehe <http://www.gnu.org/licenses/>.

# `chroot.py` is used to save references to started chroots of a certain directory (in form of the PID in a data file) so that the necessary mounts (of `/proc`, `/sys`, etc.) can be performed before the first start and the cleanup of these mounts after the last end of the managed chroots. The cleanup can be added as a system service by wrapping the `chroot_shutdown` function in python script which is invoked by `initd` or `upstart` (or something similar).

import plac
import tempfile
import chroot_globals
import logging
import os
import signal
import python_essentials
import python_essentials.lib
import python_essentials.lib.mount_utils as mount_utils
import subprocess as sp
import sys

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
ch = logging.StreamHandler()
ch.setLevel(logging.INFO)
logger.addHandler(ch)

HOST_TYPE_DEBIAN="debian"
HOST_TYPE_FREEBSD = "freebsd"
host_type_default = HOST_TYPE_DEBIAN
shell_default = "/bin/bash"
config_dir_path=os.path.join(os.getenv("HOME"), ".%s" % (chroot_globals.app_name, ))
count_file_name = "chroot_count.dta"
count_file_path_default=os.path.join(config_dir_path, count_file_name) # has to be a static path in order to keep `chroot_shutdown` parameterless
mount_default = "mount"
mount_nullfs_default="mount_nullfs"
kldload_default = "kldload"
chroot_default = "chroot"
count_file_separator = ";"
umount_default = "umount"

@plac.annotations(base_dir="The base directory of the chroot", 
)
def chroot(base_dir, shell=shell_default, count_file_path=count_file_path_default, host_type=host_type_default, mount=mount_default, mount_nullfs=mount_nullfs_default, kldload=kldload_default, chroot=chroot_default):
    """Performs the necessary preparations for starting the chroot located in `base_dir` if and only if the script is invoked the first time with the value of `base_dir` and `host_type`, starts the chroot for `base_dir` and stores a reference (in form of `base_dir`, `host_type` and the pid of the chroot shell) in a line in the file denoted by `count_file_path`. Creates the file denoted by `count_file_path` if it doesn't exist. `host_type` allows to leave some fundamental differences between hosts to the script. `base_dir` must not contain %s. It is possible to manage different host types for the same base directory (that might make sense one day or maybe even already). The chroot (shell) runs in foreground and the script can be invoked multiple times.""" % (count_file_separator, )
    if count_file_separator in count_file_path:
        # `base_dir` might be wrapped in a delimiter character when writting into the count file, but this appears to be overhead in implementation because there're few directories with `;` in it -> if that ever becomes an issue store values in a persistent map with shelve
        raise ValueError("character %s not allowed in base_dir argument" % (count_file_separator, ))
    if not os.path.exists(config_dir_path):
        logger.debug("creating config directory '%s'" % (config_dir_path, ))
        os.makedirs(config_dir_path)
    elif not os.path.isdir(config_dir_path):
        raise ValueError("config directory '%s' is not a directory" % (config_dir_path, ))
    if not os.path.exists(count_file_path):
        logger.debug("creating count file '%s'" % (count_file_path, ))
        os.mknod(count_file_path, 755)
    if os.path.isdir(count_file_path):
        raise ValueError("count file '%s' is a directory" % (count_file_path, ))
    if host_type == HOST_TYPE_FREEBSD:
        sp.call([kldload, "fdescfs", "linprocfs", "linsysfs", "tmpfs"]) # fails if one of the modules is already loaded, loads all necessary modules
    # check whether eventually mounted outside the script:
    pids = retrieve_pids(base_dir, host_type, count_file_path)
    if len(pids) > 0:
        logger.info("mounts already set up for base directory '%s' and host type '%s'" % (base_dir, host_type, ))
    else:
        chroot_start(base_dir=base_dir, host_type=host_type)
    chroot_process = sp.Popen([chroot, base_dir, shell])
    pid = chroot_process.pid
    with open(count_file_path, "w") as count_file:
        count_file_entry = "%s%s%s%s%s" % (base_dir, count_file_separator, pid, count_file_separator, host_type, )
        count_file.write("%s\n" % (count_file_entry, ))
    logger.debug("adding entry '%s' to count file '%s'" % (count_file_entry, count_file_path, ))     
    chroot_process.wait() 

def chroot_start(base_dir, host_type):
    proc = "/proc"
    sys = "/sys"
    devpts = "/dev/pts"
    dev = "/dev"
    # @TODO: handle unmounting of successful mounts if not all are successful
    proc_mount_target = os.path.join(base_dir, "proc")
    sys_mount_target = os.path.join(base_dir, "sys")
    dev_mount_target = os.path.join(base_dir, "dev")
    devpts_mount_target = os.path.join(base_dir, "dev/pts")
    if host_type == HOST_TYPE_DEBIAN:
        mount_utils.lazy_mount(proc, proc_mount_target, "proc")
        mount_utils.lazy_mount(sys, sys_mount_target, "sysfs")
        mount_utils.lazy_mount("/dev", dev_mount_target, fs_type=None, options_str="bind")
        mount_utils.lazy_mount("/dev/pts", devpts_mount_target, "devpts")
    elif host_type == HOST_TYPE_FREEBSD:
        mount_utils.lazy_mount("none", proc_mount_target, "linprocfs")
        mount_utils.lazy_mount("none", # <ref>https://forums.freebsd.org/threads/install-debian-gnu-linux-using-debootstrap-on-a-freebsd-jail-with-zfs.41470/</ref>
            dev_mount_target, "devfs")
        mount_utils.lazy_mount("none", sys_mount_target, "linsysfs")
        mount_utils.lazy_mount("none", os.path.join(base_dir, "lib/init/rw", "tmpfs"))
    else:
        raise ValueError("host_type '%s' not supported" % (str(host_type), ))
    logger.info("setup mount points for base directory '%s' and host type '%s'" % (base_dir, host_type, ))

def chroot_shutdown(count_file_path=count_file_path_default, umount=umount_default):
    """Reads the PIDs of all started instances from `count_file_path` which is expected to be created by `chroot`, terminates them and then frees the resources, i.e. unmounts the (virtual) filesystems and directories which have been mounted in `chroot`. Returns `0` on success and `1` if `count_file_path` doesn't exist."""
    # internal implementation notes:
    # - should be parameterless because this makes wrapping the function as easy as possible (see script comment as well)
    if not os.path.exists(count_file_path):
        logger.info("count file '%s' doesn't exist, canceling shutdown" % (count_file_path, ))
        return 0
    base_dir_dict = retrieve_pids_dict(count_file_path)
    for base_dir in base_dir_dict:
        proc_mount_target = os.path.join(base_dir, "proc")
        sys_mount_target = os.path.join(base_dir, "sys")
        dev_mount_target = os.path.join(base_dir, "dev")
        devpts_mount_target = os.path.join(base_dir, "dev/pts")
        host_type_dict = base_dir_dict[base_dir]
        if len(host_type_dict) > 0:            
            for host_type in host_type_dict:
                for pid in host_type_dict[host_type]:
                    try:
                        os.kill(pid, signal.SIGTERM)
                    except OSError:
                        # a real error occured or the process no longer exists (an entry doesn't denote a running chroot session, but the possibility that the mounts need to be unmounted), but in case this is called at system shutdown we really need to kill
                        pass
                # everything killed -> free resources
                if host_type == HOST_TYPE_DEBIAN:
                    sp.call([umount, devpts_mount_target]) # before dev_mount_target
                    sp.call([umount, dev_mount_target])
                    sp.call([umount, sys_mount_target])
                    sp.call([umount, proc_mount_target])
                elif host_type == HOST_TYPE_FREEBSD:
                    sp.call([umount, dev_mount_target])
                    sp.call([umount, sys_mount_target])
                    sp.call([umount, proc_mount_target])
                    sp.call([umount, os.path.join(base_dir, "lib/init/rw")])
                else:
                    raise ValueError("host_type '%s' not supported (count file '%s' corrupted)" % (host_type, count_file_path, ))
                logger.info("umounted chroot mounts for base directory '%s' and host type '%s'" % (base_dir, host_type, ))

def retrieve_pids_dict(count_file_path):
    base_dir_dict = dict()
    with open(count_file_path, "r") as count_file:
        for base_dir, pid_str, host_type in [i.strip().split(count_file_separator) for i in count_file.readlines()]:
            if not base_dir in base_dir_dict:
                base_dir_dict[base_dir] = dict()
            host_type_dict = base_dir_dict[base_dir]
            if not host_type in host_type_dict:
                host_type_dict[host_type] = []
            pid = int(pid_str)
            host_type_dict[host_type].append(pid)
    return base_dir_dict

def retrieve_pids(base_dir, host_type, count_file_path):
    """Retrieves a list of pids of chroot session currently started for `host_type` or an empty list if no pids are managed for that type."""
    base_dir_dict = retrieve_pids_dict(count_file_path)
    if not base_dir in base_dir_dict:
        return []
    if not host_type in base_dir_dict[base_dir]:
        return []
    return base_dir_dict[base_dir][host_type]

if __name__ == "__main__":
    plac.call(chroot)
