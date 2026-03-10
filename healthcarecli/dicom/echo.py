"""DICOM C-ECHO SCU — verify a PACS connection (ping)."""

from __future__ import annotations

from pynetdicom import AE
from pynetdicom.sop_class import Verification

from healthcarecli.dicom.connections import AEProfile


class DicomEchoError(RuntimeError):
    pass


def cecho(profile: AEProfile) -> float:
    """Send a C-ECHO to verify the PACS is reachable and responsive.

    Returns:
        Round-trip time in seconds.

    Raises:
        DicomEchoError: if association fails or SCP returns a failure status.
    """
    import time

    ae = AE(ae_title=profile.calling_ae)
    ae.add_requested_context(Verification)

    t0 = time.perf_counter()
    assoc = ae.associate(profile.host, profile.port, ae_title=profile.ae_title)
    if not assoc.is_established:
        raise DicomEchoError(
            f"Could not associate with {profile.ae_title}@{profile.host}:{profile.port}"
        )

    try:
        status = assoc.send_c_echo()
        elapsed = time.perf_counter() - t0
        if status is None:
            raise DicomEchoError("No response to C-ECHO (timeout)")
        if status.Status != 0x0000:
            raise DicomEchoError(f"C-ECHO failed — status 0x{status.Status:04X}")
        return elapsed
    finally:
        assoc.release()
