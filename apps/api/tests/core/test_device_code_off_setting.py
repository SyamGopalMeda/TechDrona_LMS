"""TD_DEVICE_CODE_OFF (testing phase, email not integrated): off by default; never in production."""

from app.core.config import Settings


def test_device_code_off_default_on_and_production():
    assert Settings(APP_ENV="staging").device_code_off is False
    assert Settings(APP_ENV="staging", TD_DEVICE_CODE_OFF=True).device_code_off is True
    assert Settings(APP_ENV="production", TD_DEVICE_CODE_OFF=True).device_code_off is False
