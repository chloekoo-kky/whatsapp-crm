"""Outscraper hunt provider: API contract + shared persist pipeline."""

from unittest.mock import Mock, patch

from django.test import TestCase, override_settings

from leads.models import CategoryRule, Lead, SearchQueryRecord
from leads.outscraper import collect_outscraper_maps_places, extract_outscraper_places
from leads.services import (
    FetchLeadsResult,
    _normalize_place_item,
    fetch_leads,
    fetch_leads_from_serper,
    normalize_hunt_provider,
)


def _outscraper_place(**overrides):
    place = {
        "query": "clinic Petaling Jaya Selangor Malaysia",
        "name": "Q & M Dental Clinic (PJ)",
        "place_id": "ChIJ-outscraper-place",
        "google_id": "0xabc:0xdef",
        "full_address": "1 Outscraper St, Petaling Jaya",
        "phone": "+60121111999",
        "site": "https://qnmdental.example/",
        "cid": "16524898314635901619",
        "location_link": "https://www.google.com/maps/place/Q+%26+M/@3.1,101.6,14z",
    }
    place.update(overrides)
    return place


def _json_resp(payload, status_code=200):
    resp = Mock()
    resp.status_code = status_code
    resp.raise_for_status = Mock()
    resp.json.return_value = payload
    resp.text = ""
    return resp


class HuntProviderNormalizeTests(TestCase):
    def test_blank_defaults_to_serper(self):
        self.assertEqual(normalize_hunt_provider(""), "serper")
        self.assertEqual(normalize_hunt_provider(None), "serper")

    def test_rejects_unknown(self):
        with self.assertRaises(ValueError):
            normalize_hunt_provider("google")


class OutscraperFieldNormalizeTests(TestCase):
    def test_maps_outscraper_fields_into_canonical_place(self):
        normalized = _normalize_place_item(_outscraper_place())
        self.assertEqual(normalized["name"], "Q & M Dental Clinic (PJ)")
        self.assertEqual(normalized["address"], "1 Outscraper St, Petaling Jaya")
        self.assertEqual(normalized["phone_number"], "+60121111999")
        self.assertEqual(normalized["website"], "https://qnmdental.example/")
        self.assertTrue(normalized["source_url"].startswith("https://www.google.com/maps/place/"))

    def test_extract_nested_and_flat_data_arrays(self):
        nested = {"status": "Success", "data": [[_outscraper_place()], [_outscraper_place(name="B")]]}
        flat = {"status": "Success", "data": [_outscraper_place(), _outscraper_place(name="B")]}
        self.assertEqual(len(extract_outscraper_places(nested)), 2)
        self.assertEqual(len(extract_outscraper_places(flat)), 2)


class OutscraperCollectContractTests(TestCase):
    @override_settings(OUTSCRAPER_API_KEY="test-outscraper")
    @patch("leads.outscraper.requests.get")
    def test_small_limit_uses_sync_get(self, mock_get):
        mock_get.return_value = _json_resp(
            {"id": "req-1", "status": "Success", "data": [[_outscraper_place()]]}
        )
        places, errors = collect_outscraper_maps_places(
            "clinic Petaling Jaya",
            target=20,
            api_key="test-outscraper",
            region="MY",
        )
        self.assertEqual(errors, [])
        self.assertEqual(len(places), 1)
        self.assertEqual(mock_get.call_count, 1)
        _args, kwargs = mock_get.call_args
        self.assertIn("/google-maps-search", _args[0])
        self.assertEqual(kwargs["headers"]["X-API-KEY"], "test-outscraper")
        self.assertEqual(kwargs["params"]["async"], "false")
        self.assertEqual(kwargs["params"]["limit"], 20)
        self.assertEqual(kwargs["params"]["region"], "MY")

    @override_settings(OUTSCRAPER_API_KEY="test-outscraper")
    @patch("leads.outscraper.time.sleep", return_value=None)
    @patch("leads.outscraper.requests.get")
    def test_large_limit_submits_async_and_polls_request_id(self, mock_get, _sleep):
        pending = _json_resp(
            {
                "id": "32692d16-725c-4e66-b013-95e80e873b7e",
                "status": "Pending",
                "results_location": "https://api.outscraper.cloud/requests/32692d16-725c-4e66-b013-95e80e873b7e",
            },
            status_code=202,
        )
        done = _json_resp(
            {
                "id": "32692d16-725c-4e66-b013-95e80e873b7e",
                "status": "Success",
                "data": [[_outscraper_place()], [_outscraper_place(name="Second Clinic")]],
            }
        )
        mock_get.side_effect = [pending, done]
        places, errors = collect_outscraper_maps_places(
            "clinic Petaling Jaya",
            target=40,
            api_key="test-outscraper",
            region="MY",
        )
        self.assertEqual(errors, [])
        self.assertEqual(len(places), 2)
        self.assertEqual(mock_get.call_count, 2)
        submit_url = mock_get.call_args_list[0][0][0]
        poll_url = mock_get.call_args_list[1][0][0]
        self.assertIn("/google-maps-search", submit_url)
        self.assertEqual(mock_get.call_args_list[0][1]["params"]["async"], "true")
        self.assertIn("/requests/32692d16-725c-4e66-b013-95e80e873b7e", poll_url)
        self.assertEqual(mock_get.call_args_list[1][1]["headers"]["X-API-KEY"], "test-outscraper")


class SharedPersistPipelineTests(TestCase):
    def setUp(self):
        CategoryRule.objects.create(match_phrase="dental", category="dental", priority=10)

    @override_settings(OUTSCRAPER_API_KEY="test-outscraper", HUNT_MAX_LIMIT=100)
    @patch("leads.services._persist_imported_places")
    @patch("leads.services.collect_outscraper_maps_places")
    def test_outscraper_fetch_uses_shared_persist(self, mock_collect, mock_persist):
        mock_collect.return_value = ([_outscraper_place()], [])
        mock_persist.return_value = FetchLeadsResult(
            created=1, skipped_existing=0, errors=[], places_seen=1, created_ids=[1]
        )
        fetch_leads(
            "Petaling Jaya",
            "",
            provider="outscraper",
            num=20,
            shop_keyword="clinic",
            country="Malaysia",
        )
        mock_collect.assert_called_once()
        mock_persist.assert_called_once()
        self.assertEqual(mock_persist.call_args[0][0], [_outscraper_place()])

    @override_settings(SERPER_API_KEY="test-serper", HUNT_MAX_LIMIT=100)
    @patch("leads.services._persist_imported_places")
    @patch("leads.services._collect_serper_maps_places")
    def test_serper_fetch_uses_same_persist(self, mock_collect, mock_persist):
        serper_place = {
            "title": "Serper Dental",
            "address": "2 Serper St",
            "phoneNumber": "+60121111000",
        }
        mock_collect.return_value = ([serper_place], [])
        mock_persist.return_value = FetchLeadsResult(
            created=1, skipped_existing=0, errors=[], places_seen=1, created_ids=[1]
        )
        fetch_leads_from_serper(
            "Petaling Jaya",
            "",
            num=20,
            shop_keyword="clinic",
            country="Malaysia",
        )
        mock_persist.assert_called_once()
        self.assertIs(mock_persist.call_args[0][0][0], serper_place)

    @override_settings(OUTSCRAPER_API_KEY="test-outscraper", HUNT_MAX_LIMIT=100)
    @patch("leads.services.collect_outscraper_maps_places")
    def test_outscraper_applies_tags_phone_dedup_exclude_website_and_chain(self, mock_collect):
        existing = Lead.objects.create(
            name="Other Biz",
            address="Old St",
            phone_number="+60120000001",
            phone_numbers=["+60120000001"],
        )
        mock_collect.return_value = (
            [
                _outscraper_place(
                    name="Alpha Dental",
                    full_address="10 Chain Rd",
                    phone="+60121111001",
                    site="https://alpha.example/",
                ),
                _outscraper_place(
                    name="Alpha Dental",
                    full_address="20 Chain Rd",
                    phone="+60121111002",
                    site="https://alpha-b.example/",
                    place_id="ChIJ-second",
                    cid="2",
                ),
                _outscraper_place(
                    name="Pharmacy Skip",
                    full_address="30 Exclude Rd",
                    phone="+60121111003",
                    site="https://pharm.example/",
                    place_id="ChIJ-pharm",
                    cid="3",
                ),
                _outscraper_place(
                    name="Maps Only Shop",
                    full_address="40 Maps Rd",
                    phone="+60121111004",
                    site="",
                    place_id="ChIJ-maps",
                    cid="4",
                ),
                _outscraper_place(
                    name="Dup Phone Clinic",
                    full_address="50 Phone Rd",
                    phone=existing.phone_number,
                    site="https://dup.example/",
                    place_id="ChIJ-phone",
                    cid="5",
                ),
            ],
            [],
        )
        rec = SearchQueryRecord.objects.create(keyword="clinic", search_city="Petaling Jaya")
        result = fetch_leads(
            "Petaling Jaya",
            "",
            provider="outscraper",
            num=20,
            shop_keyword="clinic",
            country="Malaysia",
            search_query_record=rec,
            require_website=True,
            exclude_keywords=["pharmacy"],
        )
        rec.refresh_from_db()
        self.assertEqual(result.created, 2)
        self.assertEqual(rec.leads_created, 2)
        self.assertEqual(rec.exclude_keywords, ["pharmacy"])
        self.assertEqual(result.skipped_excluded, 1)
        self.assertEqual(result.skipped_no_website, 1)
        self.assertEqual(result.skipped_duplicate_phone, 1)
        leads = list(Lead.objects.filter(name="Alpha Dental").order_by("address"))
        self.assertEqual(len(leads), 2)
        self.assertTrue(all(row.is_chain for row in leads))
        self.assertCountEqual(
            list(leads[0].tags.values_list("slug", flat=True)),
            ["dental"],
        )
        self.assertFalse(Lead.objects.filter(name="Pharmacy Skip").exists())
        self.assertFalse(Lead.objects.filter(name="Maps Only Shop").exists())
        self.assertFalse(Lead.objects.filter(name="Dup Phone Clinic").exists())
