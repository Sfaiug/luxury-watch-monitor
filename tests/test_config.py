"""The owner's money settings are read when configuration is imported."""

import logging
import runpy
from decimal import Decimal

import pytest

import config
import worth


SHARES = [("LEAST_PROFIT_SHARE", "least_profit_share", 0.10),
          ("SALE_FEE_SHARE", "sale_fee_share", 0.065)]
AMOUNTS = [("LEAST_PROFIT_EUR", "least_profit_eur", 500),
           ("SALE_SHIPPING_EUR", "sale_shipping_eur", 60)]


@pytest.fixture
def money_settings(monkeypatch):
    for name, _, _ in SHARES + AMOUNTS:
        monkeypatch.delenv(name, raising=False)

    def read(**values):
        for name, value in values.items():
            monkeypatch.setenv(name, value)
        # Read a fresh configuration without replacing the application's singleton.
        return runpy.run_path(config.__file__)["APP_CONFIG"]

    return read


def test_money_settings_defaults(money_settings, caplog):
    settings = money_settings()
    for _, field, default in SHARES + AMOUNTS:
        assert getattr(settings, field) == default
    assert not caplog.records


@pytest.mark.parametrize("name,field,default", SHARES)
@pytest.mark.parametrize("text,expected", [
    ("0.15", 0.15), ("0,15", 0.15), ("15", 0.15), ("15 %", 0.15),
    (" 6,5% ", 0.065), ("0", 0), ("1", 1), ("100", 1), ("100 %", 1),
    ("1 %", 0.01), ("0,15 %", 0.0015),
])
def test_money_settings_share_formats(money_settings, caplog, name, field, default, text, expected):
    settings = money_settings(**{name: text})
    assert getattr(settings, field) == pytest.approx(expected)
    assert not caplog.records


@pytest.mark.parametrize("name,field,default", AMOUNTS)
@pytest.mark.parametrize("text,expected", [("825.50", 825.5), (" 825,50 ", 825.5), ("0", 0)])
def test_money_settings_amount_formats(money_settings, caplog, name, field, default, text, expected):
    settings = money_settings(**{name: text})
    assert getattr(settings, field) == expected
    assert not caplog.records


@pytest.mark.parametrize("name,field,default", SHARES + AMOUNTS)
@pytest.mark.parametrize("text", ["", "oops", "nan", "inf", "-inf", "1e999", "-1", "15 %%", "1,2,3"])
def test_money_settings_invalid_values_use_defaults_and_warn(money_settings, caplog, name, field, default, text):
    settings = money_settings(**{name: text})
    for _, attribute, fallback in SHARES + AMOUNTS:
        assert getattr(settings, attribute) == fallback
    assert len(caplog.records) == 1
    warning = caplog.records[0]
    assert warning.levelno == logging.WARNING
    assert name in warning.getMessage()
    assert "default" in warning.getMessage()
    assert str(default) in warning.getMessage()


@pytest.mark.parametrize("name,field,default", SHARES)
@pytest.mark.parametrize("text", ["101", "101 %", "-15 %"])
def test_money_settings_shares_outside_range_use_defaults(money_settings, caplog, name, field, default, text):
    assert getattr(money_settings(**{name: text}), field) == default
    assert name in caplog.text


@pytest.mark.parametrize("name,field,default", AMOUNTS)
def test_money_settings_amounts_do_not_accept_percentages(money_settings, caplog, name, field, default):
    assert getattr(money_settings(**{name: "15 %"}), field) == default
    assert name in caplog.text


def test_money_settings_percentage_keeps_buying_limit(monkeypatch, money_settings):
    settings = money_settings(LEAST_PROFIT_SHARE="10")
    monkeypatch.setattr(worth, "APP_CONFIG", settings)
    assert worth.most_to_pay(Decimal("10000")) == Decimal("7965")


def test_money_settings_german_decimals_reach_buying_limit(monkeypatch, money_settings):
    settings = money_settings(LEAST_PROFIT_SHARE="0,15", LEAST_PROFIT_EUR="800,00",
                              SALE_FEE_SHARE="6,5 %", SALE_SHIPPING_EUR="60,00")
    monkeypatch.setattr(worth, "APP_CONFIG", settings)
    assert worth.least_profit(Decimal("4000")) == Decimal("800")
    assert worth.most_to_pay(Decimal("10000")) == Decimal("7370")
