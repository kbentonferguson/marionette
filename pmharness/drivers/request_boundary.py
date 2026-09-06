"""Observe JSON bodies at urllib Request construction, without retaining headers."""
import urllib.request


def http_request(driver, *args, **kwargs):
    request = urllib.request.Request(*args, **kwargs)
    observer = getattr(driver, '_request_body_observer', None)
    if observer is not None:
        observer(request.data)
    return request
