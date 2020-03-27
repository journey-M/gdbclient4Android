
import argparse
import os
import logging
import sys
import time
import adb 
import gdbrunner

# adb -s ENU5T15810001884 shell su 0 /data/local/tmp/arm64-gdbserver --once :5039 --attach 2329
# adb -s ENU5T15810001884 shell su 0 cat /home/guoweijie004/workspaces/testdir/jniTest/obj/local/arm64-v8a/hello-jni > /data/local/tmp/gdbclient-binary-202539 ;echo x$?

def parse_args():
    parser = gdbrunner.ArgumentParser()

    group = parser.add_argument_group(title="attach target")
    group = group.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "-p", dest="target_pid", metavar="PID", type=int,
        help="attach to a process with specified PID")
    group.add_argument(
        "-n", dest="target_name", metavar="NAME",
        help="attach to a process with specified name")
    group.add_argument(
        "-r", dest="run_cmd", metavar="CMD", nargs=argparse.REMAINDER,
        help="run a binary on the device, with args")


    parser.add_argument(
        "--port", nargs="?", default="5039",
        help="override the port used on the host")
    parser.add_argument(
        "--user", nargs="?", default="root",
        help="user to run commands as on the device [default: root]")
    parser.add_argument(
        "--file", dest="file_on_host",
        help="the binary file in gdb host system")
    return parser.parse_args()

def get_gdbserver_path(arch, ndkroot):
    path = "{}/prebuilt/android-{}/gdbserver/gdbserver"
    if arch.endswith("64"):
        return path.format(ndkroot, arch)
    else:
        return path.format(ndkroot, arch)

def get_remote_pid(device, process_name):
    processes = gdbrunner.get_processes(device)
    if process_name not in processes:
        msg = "failed to find running process {}".format(process_name)
        sys.exit(msg)
    pids = processes[process_name]
    if len(pids) > 1:
        msg = "multiple processes match '{}': {}".format(process_name, pids)
        sys.exit(msg)

    # Fetch the binary using the PID later.
    return pids[0]

def handle_switches(args, sysroot, ndkroot):
    """Fetch the targeted binary and determine how to attach gdb.

    Args:
        args: Parsed arguments.
        sysroot: Local sysroot path.

    Returns:
        (binary_file, attach_pid, run_cmd).
        Precisely one of attach_pid or run_cmd will be None.
    """

    device = args.device
    binary_file = None
    pid = None
    run_cmd = None

    if args.target_pid:
        # Fetch the binary using the PID later.
        pid = args.target_pid
    elif args.target_name:
        # Fetch the binary using the PID later.
        pid = get_remote_pid(device, args.target_name)
    elif args.run_cmd:
        if not args.run_cmd[0]:
            sys.exit("empty command passed to -r")
        if not args.run_cmd[0].startswith("/"):
            sys.exit("commands passed to -r must use absolute paths")
        # run_cmd = args.run_cmd
        # binary_file, local = gdbrunner.find_file(device, run_cmd[0], sysroot,
        #                                          user=args.user)
        binary_file, run_cmd = gdbrunner.push_return_file(device, args.run_cmd, user=args.user)


    if  binary_file is None:
        assert args.file_on_host is not None
        binary_file =  open(args.file_on_host, "rb")
        return (binary_file, pid, run_cmd)

    return (binary_file, pid, run_cmd)

def generate_gdb_script(sysroot, binary_file, is64bit, port, connect_timeout=5):
    # Generate a gdb script.
    # TODO: Detect the zygote and run 'art-on' automatically.
    # root = os.environ["ANDROID_BUILD_TOP"]

    gdb_commands = ""
    gdb_commands += "file '{}'\n".format(binary_file.name)
    # gdb_commands += "directory '{}'\n".format(binary_file)
    # gdb_commands += "set solib-absolute-prefix {}\n".format(sysroot)
    # gdb_commands += "set solib-search-path {}\n".format(solib_search_path)

    # dalvik_gdb_script = os.path.join(root, "development", "scripts", "gdb",
    #                                  "dalvik.gdb")
    # if not os.path.exists(dalvik_gdb_script):
    #     logging.warning(("couldn't find {} - ART debugging options will not " +
    #                      "be available").format(dalvik_gdb_script))
    # else:
    #     gdb_commands += "source {}\n".format(dalvik_gdb_script)

    # Try to connect for a few seconds, sometimes the device gdbserver takes
    # a little bit to come up, especially on emulators.
    gdb_commands += """
python

def target_remote_with_retry(target, timeout_seconds):
  import time
  end_time = time.time() + timeout_seconds
  while True:
    try:
      gdb.execute("target remote " + target)
      return True
    except gdb.error as e:
      time_left = end_time - time.time()
      if time_left < 0 or time_left > timeout_seconds:
        print("Error: unable to connect to device.")
        print(e)
        return False
      time.sleep(min(0.25, time_left))

target_remote_with_retry(':{}', {})

end
""".format(port, connect_timeout)

    return gdb_commands

def main():
    args = parse_args()
    device = args.device
    print (device)

    ndkroot = os.environ["NDK_ROOT"]

    sysroot = os.getcwd()
    # debug_socket = "/data/local/tmp/debug_socket"
    debug_socket = args.port
    pid = None
    run_cmd = None

    # Fetch binary for -p, -n.
    binary_file, pid, run_cmd = handle_switches(args, sysroot, ndkroot)

    with binary_file:
        
        arch = gdbrunner.get_binary_arch(binary_file)
        is64bit = arch.endswith("64")

        # Make sure we have the linker
        # ensure_linker(device, sysroot, is64bit)

        # Start gdbserver.
        gdbserver_local_path = get_gdbserver_path(arch, ndkroot)
        gdbserver_remote_path = "/data/local/tmp/{}-gdbserver".format(arch)
        gdbrunner.start_gdbserver(
            device, gdbserver_local_path, gdbserver_remote_path,
            target_pid=pid, run_cmd=run_cmd, debug_socket=debug_socket,
            port=args.port, user=args.user)

        # # Generate a gdb script.
        gdb_commands = generate_gdb_script(sysroot=sysroot,
                                           binary_file=binary_file,
                                           is64bit=is64bit,
                                           port=args.port)

        # Find where gdb is
        if sys.platform.startswith("linux"):
            platform_name = "linux-x86_64"
        elif sys.platform.startswith("darwin"):
            platform_name = "darwin-x86"
        else:
            sys.exit("Unknown platform: {}".format(sys.platform))
        gdb_path = os.path.join(ndkroot, "prebuilt", platform_name, "bin",
                                "gdb")


        # Start gdb.
        gdbrunner.start_gdb(gdb_path, gdb_commands)

    return;



if  __name__ == "__main__":
    main()
