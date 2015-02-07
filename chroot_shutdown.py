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

# a simple wrapper around the `chroot_shutdown` function in `chroot.py` which can be called from an initd or upstart script (or something similar) with the necessary privileges

import chroot
import plac

@plac.annotations(
    base_dir=("Only shutdown all resources based on `base_dir`. Effect depends on `host_type`. `None` means all.", "positional"), 
    host_type=("Only shutdown all resources with `host_type`. Effect depends on `base_dir`. `None` means all.", "positional"), 
    config_dir_path=(chroot.__docstring_config_dir_path__, "option"), 
    umount=("The umount binary to use", "option"), 
    debug=(chroot.__docstring_debug__, "flag"), 
)    
def chroot_shutdown(base_dir=None, host_type=None, config_dir_path=chroot.config_dir_path_default, umount=chroot.umount_default, debug=False):
    chroot.chroot_shutdown(config_dir_path=config_dir_path, umount=umount, debug=debug)

if __name__ == "__main__":
    plac.call(chroot_shutdown)
