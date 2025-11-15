"""
Notification Manager for SPECTRA
================================

This module contains the NotificationManager class for sending notifications.
"""

class NotificationManager:
    """
    A manager for sending notifications.
    """
    def __init__(self, config):
        self.config = config

    def send(self, message):
        """
        Sends a notification.
        """
        if not self.config.get("enabled"):
            return

        provider = self.config.get("provider")
        if provider == "placeholder":
            print(f"NOTIFICATION: {message}")
        else:
            # TODO: Add support for other notification providers
            print(f"Unknown notification provider: {provider}")
