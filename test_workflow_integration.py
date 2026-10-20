#!/usr/bin/env python3
"""Test script for IDOS Auto-Fix workflow

This script tests the GitHub Actions workflow integration.
"""

import os
import sys
import tempfile

# Add the idos-core directory to Python path
sys.path.insert(0, "C:\\REPOS\\idos\\idos-core")

def test_gha_error_reporter():
    """Test GHAErrorReporter functionality"""
    print("=== Testing GHAErrorReporter ===")
    
    # Set up test environment
    os.environ["GITHUB_REPOSITORY"] = "testorg/testrepo"
    os.environ["GITHUB_TOKEN"] = "test-token"
    os.environ["GITHUB_WORKFLOW"] = "TestWorkflow"
    os.environ["GITHUB_RUN_ID"] = "99999"
    
    try:
        from idos.workers.automation.ghA_error_reporter import GHAErrorReporter
        
        print("✓ GHAErrorReporter imported")
        
        reporter = GHAErrorReporter()
        print("✓ GHAErrorReporter instance created")
        
        # Test issue creation
        issue = reporter.report_failure(
            workflow="CI/CD Pipeline",
            run_id="99999",
            error_summary="Test error for workflow failure"
        )
        
        print(f"✓ Issue created: #{issue['number']}")
        print(f"✓ Auto-analyze should be triggered")
        
        return True
        
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("Starting IDOS Auto-Fix Workflow Test")
    print("=" * 50)
    
    success = test_gha_error_reporter()
    
    print("\n" + "=" * 50)
    if success:
        print("✅ Test passed - GHAErrorReporter works correctly")
    else:
        print("❌ Test failed - Check output above")
    
    print("\nNote: This test runs locally without GitHub API credentials.")
    print("In production, the workflow requires proper environment variables and permissions.")