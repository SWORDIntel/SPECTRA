import win32serviceutil
import win32service
import win32event
import servicemanager
import socket
from tgarchive.scheduler_service import SchedulerDaemon

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
        # TODO: Get config path from registry or a fixed location
        config_path = "spectra_config.json"
        state_path = "scheduler_state.json"
        self.scheduler = SchedulerDaemon(config_path, state_path)
        self.scheduler.start()
        win32event.WaitForSingleObject(self.hWaitStop, win32event.INFINITE)

if __name__ == '__main__':
    win32serviceutil.HandleCommandLine(SpectraSchedulerService)
