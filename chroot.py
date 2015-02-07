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
import shutil
import shelve

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
ch = logging.StreamHandler()
ch.setLevel(logging.INFO)
logger.addHandler(ch)

HOST_TYPE_DEBIAN="debian"
HOST_TYPE_FREEBSD = "freebsd"
host_type_default = HOST_TYPE_DEBIAN
shell_default = "/bin/bash"
config_dir_path_default=os.path.join(os.getenv("HOME"), ".%s" % (chroot_globals.app_name, ))
count_file_name = "chroot_count.dta"
mount_default = "mount"
mount_nullfs_default="mount_nullfs"
kldload_default = "kldload"
chroot_default = "chroot"
count_file_separator = ";"
umount_default = "umount"

__docstring_config_dir_path__ = "The path where to store the references to started sessions and other configuration files"
__docstring_debug__ = "Turn of debugging messages printed to stdout"

@plac.annotations(base_dir="The base directory of the chroot", 
    shell=("The shell to use for the chroot", "option"), 
    config_dir_path=(__docstring_config_dir_path__, "option"), 
    host_type=("An identifier for the different types of host which can be managed", "option"), 
    mount=("The mount binary to use", "option"), 
    mount_nullfs=("The mount_nullfs binary to use", "option"), 
    kldload=("The kldload binary to use", "option"), 
    chroot=("The chroot binary to use", "option"), 
    debug=(__docstring_debug__, "flag"), 
)
def chroot(base_dir, shell=shell_default, config_dir_path=config_dir_path_default, host_type=host_type_default, mount=mount_default, mount_nullfs=mount_nullfs_default, kldload=kldload_default, chroot=chroot_default, debug=False):
    """Performs the necessary preparations for starting the chroot located in `base_dir` if and only if the script is invoked the first time with the value of `base_dir` and `host_type`, starts the chroot for `base_dir` and stores a reference (in form of `base_dir`, `host_type` and the pid of the chroot shell) in a line in the file denoted by `count_file_path`. Creates the file denoted by `count_file_path` if it doesn't exist. `host_type` allows to leave some fundamental differences between hosts to the script. `base_dir` must not contain %s. It is possible to manage different host types for the same base directory (that might make sense one day or maybe even already). The chroot (shell) runs in foreground and the script can be invoked multiple times.""" % (count_file_separator, )
    # internal implementation notes:
    # - it's more elegant to let the use only determine one of configuration directory and count file and due to the the fact that count file is in configuration directory it is better to let him_her choose the configuration directory. The configuration directory can't be static because that get's us in trouble whit sudo and read-only roots (e.g. in FreeBSD jails).
    # - entries need to be removable from count file; either the count file is not human readable (in that case shelve can be used which is as easy as it can get) or it is (in that case either writing simple lines with a separator (makes deletions hard/implementation overhead) or using an XML serialization (programming overhead) would be the ways to go) -> use shelve
    if debug is True:
        logger.info("turning on debugging messages")
        logger.setLevel(logging.DEBUG)
        ch.setLevel(logging.DEBUG)
    if count_file_separator in config_dir_path:
        # `base_dir` might be wrapped in a delimiter character when writting into the count file, but this appears to be overhead in implementation because there're few directories with `;` in it -> if that ever becomes an issue store values in a persistent map with shelve
        raise ValueError("character %s not allowed in base_dir argument" % (count_file_separator, ))
    # don't create 
    if not os.path.exists(config_dir_path):
        logger.debug("creating config directory '%s'" % (config_dir_path, ))
        os.makedirs(config_dir_path)
    elif not os.path.isdir(config_dir_path):
        raise ValueError("config directory '%s' is not a directory" % (config_dir_path, ))
    count_file_path=os.path.join(config_dir_path, count_file_name)
    if not os.path.exists(count_file_path):
        logger.debug("creating count file '%s'" % (count_file_path, ))
        os.mknod(count_file_path, 0o0755)
    if os.path.isdir(count_file_path):
        # might have been changed externally
        raise ValueError("count file '%s' is a directory" % (count_file_path, ))
    base_dir_new = os.path.realpath(base_dir)
    if base_dir_new != base_dir:
        logger.debug("using absolute directory '%s' as base directory" % (base_dir_new, ))
        base_dir = base_dir_new
    if host_type == HOST_TYPE_FREEBSD:
        sp.call([kldload, "fdescfs", "linprocfs", "linsysfs", "tmpfs"]) # fails if one of the modules is already loaded, loads all necessary modules
    # check whether eventually mounted outside the script:
    pids = retrieve_pids(base_dir=base_dir, host_type=host_type, count_file_path=count_file_path)
    if len(pids) > 0:
        logger.info("mounts already set up for base directory '%s' and host type '%s'" % (base_dir, host_type, ))
    else:
        chroot_start(base_dir=base_dir, host_type=host_type, mount=mount)
    chroot_process = sp.Popen([chroot, base_dir, shell])
    pid = chroot_process.pid
    count_file_dict = shelve.open(count_file_path)
    if not base_dir in count_file_dict:
        count_file_dict[base_dir]= dict()
    base_dir_dict = count_file_dict[base_dir]
    if not host_type in base_dir_dict:
        base_dir_dict[host_type] = set()
    base_dir_dict[host_type].add(pid)
    base_dir_dict.close()
    count_file_entry = "%s%s%s%s%s" % (base_dir, count_file_separator, pid, count_file_separator, host_type, )
    logger.debug("adding entry '%s' to count file '%s'" % (count_file_entry, count_file_path, ))     
    chroot_process.wait() 
    if chroot_process.returncode != 0:
        raise RuntimeError("chroot process failed and returned with returncode %d" % (chroot_process.returncode, ))

def chroot_start(base_dir, host_type, mount=mount_default):
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
        mount_utils.lazy_mount(proc, proc_mount_target, "proc", mount=mount)
        sp.check_call([mount, "-t", "sysfs", sys, sys_mount_target])
            # mount_utils.lazy_mount doesn't work because os.makedirs fails with 
            # OSError "file exists" although it doesn't
        mount_utils.lazy_mount("/dev", dev_mount_target, fs_type=None, options_str="bind", mount=mount)
        mount_utils.lazy_mount("/dev/pts", devpts_mount_target, "devpts", mount=mount)
    elif host_type == HOST_TYPE_FREEBSD:
        mount_utils.lazy_mount("none", proc_mount_target, "linprocfs", mount=mount)
        mount_utils.lazy_mount("devfs", dev_mount_target, "devfs", mount=mount)
            # both `mount_nullfs /dev/ dev_mount_target` and `mount -t devfs none dev_mount_target` succeed, but don't initialize /dev/urandom (when read with cat; ssl fails as well)
        mount_utils.lazy_mount("none", sys_mount_target, "linsysfs", mount=mount)
        mount_utils.lazy_mount("none", os.path.join(base_dir, "lib/init/rw"), "tmpfs", mount=mount)
    else:
        raise ValueError("host_type '%s' not supported" % (str(host_type), ))
    logger.info("setup mount points for base directory '%s' and host type '%s'" % (base_dir, host_type, ))
    logger.info("copying /etc/resolv.conf into base directory '%s'" % (base_dir, ))
    resolv_target_path = os.path.join(base_dir, "etc", "resolv.conf")
    os.remove(resolv_target_path) # script leaves a broken link (either python 2.7.8 or Linux 3.16.0 or something else or everything doesn't work)
    if not os.path.exists(os.path.dirname(resolv_target_path)):
        os.makedirs(os.path.dirname(resolv_target_path))
    shutil.copyfile("/etc/resolv.conf", resolv_target_path)

def chroot_shutdown(base_dir=None, host_type=None, config_dir_path=config_dir_path_default, umount=umount_default, debug=False):
    """Reads the PIDs of all started instances from `config_dir_path/count_file_name` which is expected to be created by `chroot`, terminates them and then frees the resources, i.e. unmounts the (virtual) filesystems and directories which have been mounted in `chroot`. Returns `0` on success and `1` if `config_dir_path/count_file_name` doesn't exist."""
    # internal implementation notes:
    # - should be parameterless because this makes wrapping the function as easy as possible (see script comment as well)
    if debug is True:
        logger.info("turning on debugging messages")
        logger.setLevel(logging.DEBUG)
        ch.setLevel(logging.DEBUG)
    count_file_path=os.path.join(config_dir_path, count_file_name)
    if not os.path.exists(count_file_path):
        logger.info("count file '%s' doesn't exist, canceling shutdown" % (count_file_path, ))
        return 0
    base_dir_dict = shelve.open(count_file_path)
    if len(base_dir_dict) == 0:
        logger.info("count file '%s' is empty" % (count_file_path, ))
    for base_dir0, base_dir_dict0 in base_dir_dict.items():
        if base_dir != None and base_dir0 != base_dir:
            continue
        proc_mount_target = os.path.join(base_dir0, "proc")
        sys_mount_target = os.path.join(base_dir0, "sys")
        dev_mount_target = os.path.join(base_dir0, "dev")
        devpts_mount_target = os.path.join(base_dir0, "dev/pts")
        host_type_dict = base_dir_dict0[base_dir0]
        if len(host_type_dict) > 0:            
            for host_type0, pids in host_type_dict.items():
                if host_type != None and host_type0 != host_type:
                    continue
                for pid in pids:
                    try:
                        os.kill(pid, signal.SIGTERM)
                    except OSError:
                        # a real error occured or the process no longer exists (an entry doesn't denote a running chroot session, but the possibility that the mounts need to be unmounted), but in case this is called at system shutdown we really need to kill
                        pass
                # everything killed -> free resources
                if host_type0 == HOST_TYPE_DEBIAN:
                    sp.call([umount, devpts_mount_target]) # before dev_mount_target
                    sp.call([umount, dev_mount_target])
                    sp.call([umount, sys_mount_target])
                    sp.call([umount, proc_mount_target])
                elif host_type0 == HOST_TYPE_FREEBSD:
                    sp.call([umount, dev_mount_target])
                    sp.call([umount, sys_mount_target])
                    sp.call([umount, proc_mount_target])
                    sp.call([umount, os.path.join(base_dir0, "lib/init/rw")])
                else:
                    raise ValueError("host_type '%s' not supported (count file '%s' corrupted)" % (host_type0, count_file_path, ))
                logger.info("umounted chroot mounts for base directory '%s' and host type '%s'" % (base_dir0, host_type0, ))
                host_type_dict.pop(host_type0)

def retrieve_pids(base_dir, host_type, count_file_path):
    """Retrieves a list of pids of chroot session currently started for `host_type` or an empty list if no pids are managed for that type."""
    base_dir_dict = shelve.open(count_file_path)
    if not base_dir in base_dir_dict:
        return []
    if not host_type in base_dir_dict[base_dir]:
        return []
    return base_dir_dict[base_dir][host_type]

if __name__ == "__main__":
    plac.call(chroot)
