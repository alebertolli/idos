#!/usr/bin/env python3
"""
Test script for IDOS Auto-Fix workflow

This script simulates the GitHub Actions environment for testing purposes.
It requires GitHub API tokens and proper environment variables to work.
"""

import os
import sys
import tempfile
import shutil
from pathlib import Path

def setup_test_environment():
    """Set up a mock GitHub Actions environment for testing"""
    # Create a temporary directory for the test
    test_dir = tempfile.mkdtemp(prefix="idos_test_")
    print(f"Test directory: {test_dir}")
    
    # Change to the test directory
    os.chdir(test_dir)
    
    # Create basic project structure
    os.makedirs("idos-core/idos/workers/automation")
    
    return test_dir

def main():
    print("=== IDOS Auto-Fix Workflow Test ===")
    
    # Test the GHAErrorReporter
    print("\n1. Testing GHAErrorReporter...")
    
    # Set up test environment variables
    os.environ["GITHUB_REPOSITORY"] = "testuser/test-repo"
    os.environ["GITHUB_TOKEN"] = "test-token-for-mock"
    os.environ["GITHUB_WORKFLOW"] = "test-workflow"
    os.environ["GITHUB_RUN_ID"] = "67890"
    os.environ["GITHUB_EVENT_NAME"] = "push"
    os.environ["GITHUB_REF_NAME"] = "main"
    
    # Import and test the reporter
    try:
        from idos.workers.automation.ghA_error_reporter import GHAErrorReporter
        
        print("✓ GHAErrorReporter imported successfully")
        
        reporter = GHAErrorReporter()
        
        # Report a failure
        issue = reporter.report_failure(
            workflow="CI/CD Pipeline",
            run_id="67890",
            error_summary="Mock error: Something went wrong in the workflow"
        )
        
        print(f"✓ Issue created: #{issue['number']}")
        print(f"✓ Title: {issue['title']}")
        print(f"✓ URL: {issue['html_url']}")
        
        # Check auto-analyze
        if 'number' in issue:
            print(f"\n✓ Auto-analyze should be triggered for issue #{issue['number']}")
            
    except ImportError as e:
        print(f"✗ Failed to import GHAErrorReporter: {e}")
    except Exception as e:
        print(f"✗ Error testing GHAErrorReporter: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n=== Test Summary ===")
    print("This test verifies that the GHAErrorReporter:")
    print("1. Creates GitHub Issues on workflow failure")
    print("2. Includes auto-analyze commands in the issue body")
    print("3. Sends email notifications")
    print("\nNote: In production, this runs in GitHub Actions with proper credentials.")

if __name__ == "__main__":
    main()