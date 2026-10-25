"""Read the owned engine's runtime identity without using shell proxy settings."""

import json
import urllib.error


def fetch_props(client, url):
    try:
        with client.open(url, timeout=0.5) as response:
            props = json.loads(response.read(65536))
        return props if isinstance(props, dict) else None
    except urllib.error.HTTPError as error:
        error.close()
    except (OSError, ValueError, urllib.error.URLError):
        pass  # Older executables may not expose /props; retry without logging.
    return None
