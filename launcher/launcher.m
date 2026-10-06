/*
 * Native launcher for EQ Recorder.app (see the launcher comment in build_app.sh).
 *
 * 1) If com.eq.recorder is already running, activates that process and exits
 *    before Python starts. Two bundles in different folders have different
 *    paths, so LaunchServices does not deduplicate them, and the Python-side
 *    check (config.running_instance_pid) only runs after the .venv has been
 *    read from ~/Desktop, where a duplicate would block on the macOS folder
 *    access prompt.
 * 2) Otherwise runs Python IN THIS SAME process (Py_BytesMain), without exec:
 *    Homebrew's framework python re-launches itself as Python.app, and macOS
 *    would then register the app as org.python.python instead of
 *    com.eq.recorder.
 *
 * VENV_PYTHON is supplied by build_app.sh (-D...). boot.py is looked up next
 * to the binary (../Resources/boot.py) so a copied bundle works the same way.
 */
#include <Python.h>
#import <AppKit/AppKit.h>
#include <libgen.h>
#include <limits.h>
#include <mach-o/dyld.h>

static int activate_running_instance(void) {
    @autoreleasepool {
        NSString *bid = [[NSBundle mainBundle] bundleIdentifier];
        if (bid == nil) return 0;
        pid_t me = getpid();
        for (NSRunningApplication *app in
             [NSRunningApplication runningApplicationsWithBundleIdentifier:bid]) {
            if (app.processIdentifier != me && !app.terminated) {
                [app activateWithOptions:NSApplicationActivateAllWindows];
                fprintf(stderr, "EQ Recorder: already running (pid %d), activated it\n",
                        app.processIdentifier);
                return 1;
            }
        }
    }
    return 0;
}

int main(int argc, char **argv) {
    (void)argc;
    if (activate_running_instance()) return 0;

    char exe[PATH_MAX], real[PATH_MAX], boot[PATH_MAX];
    uint32_t size = sizeof(exe);
    if (_NSGetExecutablePath(exe, &size) != 0 || !realpath(exe, real)) {
        fprintf(stderr, "EQ Recorder: cannot resolve executable path\n");
        return 1;
    }
    snprintf(boot, sizeof(boot), "%s/../Resources/boot.py", dirname(real));

    /* The same mechanism the bin/python3.10 stub uses to hand the venv to
     * the interpreter: sys.executable/sys.prefix point into .venv. */
    setenv("__PYVENV_LAUNCHER__", VENV_PYTHON, 1);

    /* Arguments from LaunchServices (the old "-psn_…") are ignored. */
    char *args[] = { argv[0], boot, NULL };
    return Py_BytesMain(2, args);
}
