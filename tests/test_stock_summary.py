import httpx
import pytest

from idx_market.scraper import IDXStockSummaryClient


SAMPLE = {"draw": 0, "recordsTotal": 1, "recordsFiltered": 1, "data": [{"Date": "2026-09-07T00:00:00", "StockCode": "AADI", "StockName": "Adaro Andalan Indonesia Tbk.", "Previous": 11250.0, "OpenPrice": 11250.0, "High": 11850.0, "Low": 11250.0, "Close": 11700.0, "Change": 450.0, "Volume": 18108700.0, "Value": 211702077500.0, "Frequency": 8367.0, "Offer": 11700.0, "OfferVolume": 225900.0, "Bid": 11675.0, "BidVolume": 16600.0, "ForeignSell": 4375600.0, "ForeignBuy": 7631200.0}]}


def test_fetch_maps_idx_response_and_sends_paging_parameters() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["length"] == "9999"
        assert request.url.params["start"] == "0"
        assert request.headers["referer"] == "https://www.idx.co.id/id/data-pasar/ringkasan-perdagangan/ringkasan-saham"
        return httpx.Response(200, json=SAMPLE)
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        rows = IDXStockSummaryClient(client=http).fetch()
    assert rows[0].ticker == "AADI"
    assert rows[0].close == 11700.0
    assert rows[0].foreign_buy == 7631200.0


def test_fetch_explains_forbidden_response() -> None:
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(403))) as http:
        with pytest.raises(PermissionError, match="does not bypass"):
            IDXStockSummaryClient(client=http).fetch()


@pytest.mark.parametrize("length,start", [(0, 0), (10_000, 0), (1, -1)])
def test_fetch_rejects_invalid_paging(length: int, start: int) -> None:
    client = IDXStockSummaryClient(client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200))))
    with pytest.raises(ValueError):
        client.fetch(length=length, start=start)
