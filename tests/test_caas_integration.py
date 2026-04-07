import asyncio
import json
from pathlib import Path
from tgarchive.osint.caas.profiler_v2 import CAASProfilerV2
from tgarchive.db import SpectraDB
from tgarchive.osint.caas.schema import ensure_schema

def test_integration():
    profiler = CAASProfilerV2()
    
    # Test message with criminal service and threat indicators
    content = "New RDP access for sale! US/UK/EU. Price: $50. Payment: BTC. Check our shop: marketplace.onion. CVE-2024-1234 exploit included."
    
    print(f"Analyzing content: {content}")
    profile = profiler.profile_message(content, sender_username="test_seller")
    
    print("\n--- Profile Results ---")
    print(f"Confidence: {profile.confidence}")
    print(f"Categories: {profile.service_categories}")
    print(f"Payment: {profile.payment_methods}")
    print(f"Threat Indicators: {len(profile.threat_indicators)}")
    
    for ind in profile.threat_indicators:
        print(f"  - [{ind['level']}] {ind['type']}: {ind['value']} (Severity: {ind['severity']})")

    # Verify high-severity threat detection
    has_high_threat = any(ind['severity'] >= 3.0 for ind in profile.threat_indicators)
    print(f"\nHigh severity threats detected: {has_high_threat}")
    
    # Test DB saving
    db_path = "test_spectra.db"
    if Path(db_path).exists():
        Path(db_path).unlink()
        
    db = SpectraDB(db_path)
    ensure_schema(db)
    
    print("\nSaving profile to DB...")
    profiler.save_profile(db, channel_id=12345, message_id=67890, profile=profile)
    
    # Verify alert generation
    alerts = db.conn.execute("SELECT severity, summary, score FROM caas_alert").fetchall()
    print(f"\nAlerts generated: {len(alerts)}")
    for alert in alerts:
        print(f"  - [{alert[0]}] {alert[1]} (Score: {alert[2]})")

    if Path(db_path).exists():
        Path(db_path).unlink()

if __name__ == "__main__":
    test_integration()
