#
# Copyright (C) 2015 The Android Open Source Project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

"""Helpers used by both gdbclient.py and ndk-gdb.py."""

import adb
import argparse
import atexit
import os
import subprocess
import sys
import tempfile

class ArgumentParser(argparse.ArgumentParser):
    """ArgumentParser subclass that provides adb device selection."""

    def __init__(self):
        super(ArgumentParser, self).__init__()
        self.add_argument(
            "--adb", dest="adb_path",
            help="Use specific adb command")

        group = self.add_argument_group(title="device selection")
        group = group.add_mutually_exclusive_group()
        group.add_argument(
            "-a", action="store_const", dest="device", const="-a",
            help="directs commands to all interfaces")
        group.add_argument(
            "-d", action="store_const", dest="device", const="-d",
            help="directs commands to the only connected USB device")
        group.add_argument(
            "-e", action="store_const", dest="device", const="-e",
            help="directs commands to the only connected emulator")
        group.add_argument(
            "-s", metavar="SERIAL", action="store", dest="serial",
            help="directs commands to device/emulator with the given serial")

    def parse_args(self, args=None, namespace=None):
        result = super(ArgumentParser, self).parse_args(args, namespace)

        adb_path = result.adb_path or "adb"

        # Try to run the specified adb command
        try:
            subprocess.check_output([adb_path, "version"],
                                    stderr=subprocess.STDOUT)
        except (OSError, subprocess.CalledProcessError):
            msg = "ERROR: Unable to run adb executable (tried '{}')."
            if not result.adb_path:
                msg += "\n       Try specifying its location with --adb."
            sys.exit(msg.format(adb_path))

        try:
            if result.device == "-a":
                result.device = adb.get_device(adb_path=adb_path)
            elif result.device == "-d":
                result.device = adb.get_usb_device(adb_path=adb_path)
            elif result.device == "-e":
                result.device = adb.get_emulator_device(adb_path=adb_path)
            else:
                result.device = adb.get_device(result.serial, adb_path=adb_path)
        except (adb.DeviceNotFoundError, adb.NoUniqueDeviceError, RuntimeError):
            # Don't error out if we can't find a device.
            result.device = None

        return result


def get_run_as_cmd(user, cmd):
    """Generate a run-as or su command depending on user."""

    if user is None:
        return cmd
    elif user == "root":
        return ["su", "0"] + cmd
    else:
        return ["run-as", user] + cmd


def get_processes(device):
    """Return a dict from process name to list of running PIDs on the device."""

    # Some custom ROMs use busybox instead of toolbox for ps. Without -w,
    # busybox truncates the output, and very long package names like
    # com.exampleisverylongtoolongbyfar.plasma exceed the limit.
    #
    # Perform the check for this on the device to avoid an adb roundtrip
    # Some devices might not have readlink or which, so we need to handle
    # this as well.

    ps_script = """
        if [ ! -x /system/bin/readlink -o ! -x /system/bin/which ]; then
            ps;
        elif [ $(readlink $(which ps)) == "toolbox" ]; then
            ps;
        else
            ps -w;
        fi
    """
    ps_script = " ".join([line.strip() for line in ps_script.splitlines()])

    output, _ = device.shell([ps_script])

    processes = dict()
    output =  bytes.decode(output).replace("\r", "").splitlines()
    columns = output.pop(0).split()
    try:
        pid_column = columns.index("PID")
    except ValueError:
        pid_column = 1
    while output:
        columns = output.pop().split()
        process_name = columns[-1]
        pid = int(columns[pid_column])
        if process_name in processes:
            processes[process_name].append(pid)
        else:
            processes[process_name] = [pid]

    return processes


def get_pids(device, process_name):
    processes = get_processes(device)
    return processes.get(process_name, [])


def start_gdbserver(device, gdbserver_local_path, gdbserver_remote_path,
                    target_pid, run_cmd, debug_socket, port, user=None):
    """Start gdbserver in the background and forward necessary ports.

    Args:
        device: ADB device to start gdbserver on.
        gdbserver_local_path: Host path to push gdbserver from, can be None.
        gdbserver_remote_path: Device path to push gdbserver to.
        target_pid: PID of device process to attach to.
        run_cmd: Command to run on the device.
        debug_socket: Device path to place gdbserver unix domain socket.
        port: Host port to forward the debug_socket to.
        user: Device user to run gdbserver as.

    Returns:
        Popen handle to the `adb shell` process gdbserver was started with.
    """

    assert target_pid is None or run_cmd is None

    # Push gdbserver to the target.
    if gdbserver_local_path is not None:
        device.push(gdbserver_local_path, gdbserver_remote_path)

    # Run gdbserver.
    gdbserver_cmd = [gdbserver_remote_path, "--once",
                     ":{}".format(debug_socket)]

    if target_pid is not None:
        gdbserver_cmd += ["--attach", str(target_pid)]
    else:
        gdbserver_cmd += run_cmd

    device.forward("tcp:{}".format(port),
                   "tcp:{}".format(debug_socket))
    atexit.register(lambda: device.forward_remove("tcp:{}".format(port)))
    gdbserver_cmd = get_run_as_cmd(user, gdbserver_cmd)

    # Use ppid so that the file path stays the same.
    gdbclient_output_path = os.path.join(tempfile.gettempdir(),
                                         "gdbclient-{}".format(os.getppid()))
    print ("Redirecting gdbclient output to {}".format(gdbclient_output_path))
    gdbclient_output = open(gdbclient_output_path, 'w')
    return device.shell_popen(gdbserver_cmd, stdout=gdbclient_output,
                              stderr=gdbclient_output)


def push_return_file(device, run_cmd, user=None):
    executable_path = run_cmd[0]
    if not os.path.isabs(executable_path):
        raise ValueError("'{}' is not an absolute path".format(executable_path)) 

    head , tail = os.path.split(executable_path)
    remote_temp_path = "/data/local/tmp/{}".format(tail)
    device.push(executable_path, remote_temp_path);

    run_cmd[0] = remote_temp_path
    # run_cmd = '{} '.format(remote_temp_path)
    return open(executable_path ,'rb'), run_cmd;


def get_binary_arch(binary_file):
    """Parse a binary's ELF header for arch."""
    try:
        binary_file.seek(0)
        binary = binary_file.read(0x14)
    except IOError:
        raise RuntimeError("failed to read binary file")
    ei_class = (binary[0x4]) # 1 = 32-bit, 2 = 64-bit
    ei_data = (binary[0x5]) # Endianness

    assert ei_class == 1 or ei_class == 2
    if ei_data != 1:
        raise RuntimeError("binary isn't little-endian?")

    e_machine = (binary[0x13]) << 8 | (binary[0x12])
    if e_machine == 0x28:
        assert ei_class == 1
        return "arm"
    elif e_machine == 0xB7:
        assert ei_class == 2
        return "arm64"
    elif e_machine == 0x03:
        assert ei_class == 1
        return "x86"
    elif e_machine == 0x3E:
        assert ei_class == 2
        return "x86_64"
    elif e_machine == 0x08:
        if ei_class == 1:
            return "mips"
        else:
            return "mips64"
    else:
        raise RuntimeError("unknown architecture: 0x{:x}".format(e_machine))


def start_gdb(gdb_path, gdb_commands, gdb_flags=None):
    """Start gdb in the background and block until it finishes.

    Args:
        gdb_path: Path of the gdb binary.
        gdb_commands: Contents of GDB script to run.
        gdb_flags: List of flags to append to gdb command.
    """

    with tempfile.NamedTemporaryFile() as gdb_script:
        gdb_script.write(str.encode(gdb_commands))
        gdb_script.flush()
        gdb_args = [gdb_path, "-x", gdb_script.name] + (gdb_flags or [])
        gdb_process = subprocess.Popen(gdb_args)
        while gdb_process.returncode is None:
            try:
                gdb_process.communicate()
            except KeyboardInterrupt:
                pass

