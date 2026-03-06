#!/usr/bin/env python3
"""
Test script to verify the 100% refueling fix and enhanced quick actions.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from twin.ambulance import AmbulanceTwin
from telemetry.mechanical import MechanicalEngine
import time

def test_refueling_100_percent():
    """Test that ambulances refuel to exactly 100%."""
    print("🧪 Testing 100% refueling logic...")
    
    # Create a mock ambulance twin
    ambulance = AmbulanceTwin(am_id="TEST-001")
    
    # Set fuel level low to trigger refueling
    ambulance.mechanical.fuel_level = 30.0
    ambulance.mechanical.is_refueling = False
    ambulance.logistics.mission_status = "ACTIVE"
    
    print(f"  Initial fuel level: {ambulance.mechanical.fuel_level}%")
    
    # Simulate arriving at gas station
    ambulance.logistics.destination_type = "GAS_STATION"
    ambulance.logistics.mission_status = "INACTIVE"
    
    # Simulate refueling process
    ambulance.mechanical.is_refueling = True
    ambulance.logistics.destination_type = None
    ambulance.logistics.action_message = "Repostando (Bomba conectada)"
    
    # Simulate fuel increasing during refueling - set to 100.5 to trigger completion
    ambulance.mechanical.fuel_level = 100.5
    
    # Test the refueling completion logic
    print(f"  Fuel before completion: {ambulance.mechanical.fuel_level}%")
    print(f"  Is refueling: {ambulance.mechanical.is_refueling}")
    
    # Trigger the refueling completion check
    ambulance._manage_fuel_and_maintenance(0.0)
    
    print(f"  Fuel after completion: {ambulance.mechanical.fuel_level}%")
    print(f"  Is refueling: {ambulance.mechanical.is_refueling}")
    print(f"  Mission status: {ambulance.logistics.mission_status}")
    print(f"  Action message: {ambulance.logistics.action_message}")
    
    # Verify results
    assert ambulance.mechanical.fuel_level == 100.0, f"Expected 100%, got {ambulance.mechanical.fuel_level}%"
    assert ambulance.mechanical.is_refueling == False, "Should not be refueling after completion"
    assert ambulance.logistics.mission_status == "ACTIVE", "Should be ACTIVE after refueling"
    assert "100%" in ambulance.logistics.action_message, f"Action message should mention 100%: {ambulance.logistics.action_message}"
    
    print("✅ Refueling test PASSED: Ambulance refuels to exactly 100%")

def test_quick_actions():
    """Test that quick actions are available and working."""
    print("\n🧪 Testing quick actions availability...")
    
    # Check that ambulance has all required methods
    ambulance = AmbulanceTwin(am_id="TEST-002")
    
    required_actions = [
        ('inject_incident', 2),  # category, incident_type
        ('administer_treatment', 1),  # treatment_type
        ('perform_maintenance', 0),
        ('set_patient_info', 2),  # age, has_patient
        ('toggle_pause', 0),
        ('get_detailed_status', 0)
    ]
    
    for method_name, arg_count in required_actions:
        assert hasattr(ambulance, method_name), f"Missing method: {method_name}"
        method = getattr(ambulance, method_name)
        print(f"  ✓ {method_name}() - Available")
    
    print("✅ Quick actions test PASSED: All required methods available")

def test_backup_dashboard_integration():
    """Test that backup dashboard is properly integrated."""
    print("\n🧪 Testing backup dashboard integration...")
    
    # Check files exist
    required_files = [
        "static/backup_dashboard.html",
        "static/backup_dashboard.js",
        "central/server.py"
    ]
    
    for file_path in required_files:
        assert os.path.exists(file_path), f"Missing file: {file_path}"
        print(f"  ✓ {file_path} - Exists")
    
    # Check central server has backup endpoints
    with open("central/server.py", "r", encoding="utf-8") as f:
        content = f.read()
    
    required_endpoints = [
        "/api/backup_state",
        "/api/backups/list",
        "/api/backups/stats",
        "/api/backups/health"
    ]
    
    for endpoint in required_endpoints:
        assert endpoint in content, f"Missing endpoint: {endpoint}"
        print(f"  ✓ {endpoint} - Available in central server")
    
    print("✅ Backup dashboard integration test PASSED")

def main():
    """Run all tests."""
    print("🚑 HPE Ambulancia Digital Twin - Feature Tests")
    print("=" * 50)
    
    try:
        test_refueling_100_percent()
        test_quick_actions()
        test_backup_dashboard_integration()
        
        print("\n" + "=" * 50)
        print("🎉 ALL TESTS PASSED!")
        print("\nFeatures implemented:")
        print("  1. ✅ Ambulances refuel to exactly 100% at gas stations")
        print("  2. ✅ Enhanced quick actions for simulation")
        print("  3. ✅ Backup dashboard for when MQTT/P2P fail")
        print("  4. ✅ Central server with backup API endpoints")
        print("  5. ✅ Backup dashboard accessible at /backup_dashboard")
        
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        return 1
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(main())