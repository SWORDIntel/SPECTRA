"""
Attribution Formatter for SPECTRA
=================================

This module contains the AttributionFormatter class for formatting attributions.
"""

class AttributionFormatter:
    """
    A class for formatting attributions.
    """
    def __init__(self, config):
        self.config = config
        self.template = self.config.get("attribution", {}).get("template", "")
        self.timestamp_format = self.config.get("attribution", {}).get("timestamp_format", "%Y-%m-%d %H:%M:%S")
        self.style = self.config.get("attribution", {}).get("style", "text")
        self.attribution_cache = {}

    def format_attribution(self, message, source_channel_name, source_channel_id, sender_name, sender_id, timestamp):
        """
        Formats an attribution for a message.
        """
        if message.id in self.attribution_cache:
            return self.attribution_cache[message.id]

        formatted_timestamp = timestamp.strftime(self.timestamp_format)

        template_params = {
            "source_channel_name": source_channel_name,
            "source_channel_id": source_channel_id,
            "sender_name": sender_name,
            "sender_id": sender_id,
            "timestamp": formatted_timestamp,
            "message_id": message.id
        }

        if self.style == "json":
            attribution = json.dumps(template_params)
        else:
            if self.config.get("attribution", {}).get("preserve_message_id", False):
                attribution = self.template.format(**template_params)
            else:
                template_params["message_id"] = "N/A"
                attribution = self.template.format(**template_params)

        self.attribution_cache[message.id] = attribution
        return attribution
