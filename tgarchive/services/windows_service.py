import win32serviceutil
import win32service
import win32event
import servicemanager
import socket
import winreg
from tgarchive.services.scheduler_service import SchedulerDaemon

class SpectraSchedulerService(win32serviceutil.ServiceFramework):
    _svc_name_ = "SpectraScheduler"
    _svc_display_name_ = "SPECTRA Scheduler Service"

    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.hWaitStop = win32event.CreateEvent(None, 0, 0, None)
        socket.setdefaulttimeout(60)
        self.scheduler = None

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        if self.scheduler:
            self.scheduler.stop()
        win32event.SetEvent(self.hWaitStop)

    def SvcDoRun(self):
        servicemanager.LogMsg(servicemanager.EVENTLOG_INFORMATION_TYPE,
                              servicemanager.PYS_SERVICE_STARTED,
                              (self._svc_name_, ''))
        self.main()

    def main(self):
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\SPECTRA", 0, winreg.KEY_READ)
        config_path = winreg.QueryValueEx(key, "ConfigPath")[0]
        state_path = winreg.QueryValueEx(key, "StatePath")[0]
        winreg.CloseKey(key)

        self.scheduler = SchedulerDaemon(config_path, state_path)
        self.scheduler.start()
        win32event.WaitForSingleObject(self.hWaitStop, win32event.INFINITE)

if __name__ == '__main__':
    win32serviceutil.HandleCommandLine(SpectraSchedulerService)
