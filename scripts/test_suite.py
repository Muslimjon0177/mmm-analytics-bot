#!/usr/bin/env python3
"""
MMM Analytics Bot — Comprehensive Automated Test Suite
Runs end-to-end regression tests across all core application layers:
1. Database Repository (libSQL / SQLite abstraction)
2. AI Message Parser (Naqd vs Nasiya, 3-zeros rule, USD extraction)
3. Central Bank Currency API & in-memory cache
4. In-Memory Excel Workbook Generation
5. Flask Web API & Health Check endpoints
"""

import sys
import os
import io
import unittest
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass

# Add project root to path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

import config
import database
import ai_parser
import currency
import excel_export
from webapp import app

class TestMMMAnalyticsBot(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        print("\n" + "=" * 65)
        print("  MMM ANALYTICS BOT — TEST SUITE ISHGA TUSHMOQDA")
        print("=" * 65)
        database.init_db()

    def test_01_database_health_and_records(self):
        """1. Database repository va ulanish salomatligini tekshirish"""
        is_healthy = database.health_check()
        self.assertTrue(is_healthy, "Database health check muvaffaqiyatsiz bo'ldi!")

        # Yozuv saqlash va tekshirish
        rec_id = database.save_record(
            category="naqd",
            item_name="Test Olmanok",
            quantity=2,
            price=170, # 3-nol qoidasi bo'yicha 170 000 bo'lishi kerak
            total_amount=340000,
            raw_message="Test xabar"
        )
        self.assertIsNotNone(rec_id, "Yozuv saqlanmadi!")

        # Filtrlangan qidiruv
        records = database.get_filtered_records(category="naqd", search="Olmanok", limit=5)
        self.assertGreaterEqual(len(records), 1)
        self.assertEqual(records[0]["item_name"], "Test Olmanok")
        self.assertEqual(records[0]["price"], 170000)

        # Tozalash
        client = database.get_client()
        client.execute("DELETE FROM records WHERE id = ?", [rec_id])
        client.close()
        print("✅ 1. Database Repository & libSQL driver: PASSED")

    def test_02_customer_crm_ledger(self):
        """2. Mijozlar qarz daftari (CRM ledger) hisob-kitobini tekshirish"""
        test_client_name = "Sinov Klient Rustam"

        # Nasiya yozish
        nasiya_id = database.save_record(
            category="nasiya",
            partner_name=test_client_name,
            item_name="Sement M-500",
            quantity=10,
            price=60000,
            total_amount=600000
        )

        customers = database.get_all_customers(search="Rustam")
        self.assertGreaterEqual(len(customers), 1)
        cust = customers[0]
        self.assertEqual(cust["current_balance"], 600000)
        self.assertEqual(cust["total_credit"], 600000)

        # Pul to'lash (pul_keldi)
        pul_id = database.save_record(
            category="pul_keldi",
            partner_name=test_client_name,
            total_amount=200000
        )

        customers_updated = database.get_all_customers(search="Rustam")
        cust_updated = customers_updated[0]
        self.assertEqual(cust_updated["current_balance"], 400000) # 600k - 200k = 400k qarz
        self.assertEqual(cust_updated["total_paid"], 200000)

        # Tozalash
        client = database.get_client()
        client.execute("DELETE FROM records WHERE id IN (?, ?)", [nasiya_id, pul_id])
        client.execute("DELETE FROM customers WHERE name = ?", [database.normalize_partner_name(test_client_name).lower()])
        client.close()
        print("✅ 2. Mijozlar Bazasi (CRM Ledger) hisob-kitobi: PASSED")

    def test_03_ai_parser_rules(self):
        """3. AI tahlilchi qoidalari (Naqd, Nasiya, 3 ta nol, Dollar)"""
        # A) Naqd savdo (ism yo'q)
        res_naqd = ai_parser.analyze_message("2ta olmanok 170 dan")
        self.assertTrue(res_naqd.get("is_relevant"))
        rec_naqd = res_naqd["records"][0]
        self.assertEqual(rec_naqd["category"], "naqd")
        self.assertEqual(rec_naqd["price"], 170000)
        self.assertEqual(rec_naqd["total_amount"], 340000)
        self.assertIsNone(rec_naqd.get("partner_name"))

        # B) Nasiya savdo (ism bor)
        res_nasiya = ai_parser.analyze_message("Akmal aka 5 ta sement 65 dan")
        self.assertTrue(res_nasiya.get("is_relevant"))
        rec_nasiya = res_nasiya["records"][0]
        self.assertEqual(rec_nasiya["category"], "nasiya")
        self.assertEqual(rec_nasiya["price"], 65000)
        self.assertIsNotNone(rec_nasiya.get("partner_name"))

        # C) Dollar to'lovi
        res_usd = ai_parser.analyze_message("Jamshiddan (100$) pul keldi")
        self.assertTrue(res_usd.get("is_relevant"))
        rec_usd = res_usd["records"][0]
        self.assertEqual(rec_usd["category"], "pul_keldi")
        self.assertEqual(rec_usd.get("currency"), "USD")
        self.assertEqual(rec_usd.get("amount_usd"), 100.0)

        print("✅ 3. AI Parser (Naqd, Nasiya, 3 ta nol, Dollar qoidalari): PASSED")

    def test_04_currency_cbu_service(self):
        """4. Markaziy Bank valyuta kursi servisi"""
        rate = currency.get_usd_rate()
        self.assertIsInstance(rate, float)
        self.assertGreater(rate, 10000.0)
        print(f"✅ 4. CBU Currency Service (1 USD = {rate:,.2f} UZS): PASSED")

    def test_05_in_memory_excel_export(self):
        """5. Xotiradagi (in-memory) Excel eksporti"""
        mock_records = [
            {"category": "naqd", "id": 1, "date_str": "2026-11-08", "time_str": "12:00:00", "item_name": "Olmanok", "quantity": 2, "unit": "ta", "price": 170000, "total_amount": 340000, "sender_name": "Admin"},
            {"category": "nasiya", "id": 2, "date_str": "2026-11-08", "time_str": "12:05:00", "partner_name": "Akmal aka", "item_name": "Sement", "quantity": 5, "unit": "qop", "price": 65000, "total_amount": 325000, "sender_name": "Admin"},
            {"category": "pul_keldi", "id": 3, "date_str": "2026-11-08", "time_str": "12:10:00", "partner_name": "Jamshid", "total_amount": 1200000, "currency": "USD", "amount_usd": 100, "exchange_rate": 12000, "sender_name": "Admin"}
        ]
        buf = excel_export.create_excel_report(mock_records)
        self.assertIsInstance(buf, io.BytesIO)
        byte_data = buf.getvalue()
        self.assertGreater(len(byte_data), 1000)
        self.assertTrue(byte_data.startswith(b"PK\x03\x04")) # ZIP / XLSX imzosi
        print(f"✅ 5. In-Memory Excel Generation ({len(byte_data)} bytes): PASSED")

    def test_06_flask_api_and_health(self):
        """6. Flask REST API va Health Check endpointlari"""
        client = app.test_client()

        # Health endpoint
        resp_health = client.get("/health")
        self.assertEqual(resp_health.status_code, 200)
        data_health = resp_health.get_json()
        self.assertEqual(data_health["status"], "healthy")
        self.assertEqual(data_health["database"], "connected")

        # Stats endpoint
        resp_stats = client.get("/api/stats?period=7days")
        self.assertEqual(resp_stats.status_code, 200)
        data_stats = resp_stats.get_json()
        self.assertIn("kpi", data_stats)
        self.assertIn("chart", data_stats)

        # Customers endpoint
        resp_cust = client.get("/api/customers")
        self.assertEqual(resp_cust.status_code, 200)

        # Excel API stream
        resp_excel = client.get("/api/export-excel")
        self.assertEqual(resp_excel.status_code, 200)
        self.assertEqual(resp_excel.mimetype, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.assertGreater(len(resp_excel.data), 1000)

        print("✅ 6. Flask Web API & /health Check: PASSED")

if __name__ == "__main__":
    unittest.main(verbosity=1)
