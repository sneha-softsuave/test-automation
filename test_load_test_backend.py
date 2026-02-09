"""Test script to verify load testing backend implementation."""

import sys
from pathlib import Path

# Add app to path
sys.path.insert(0, str(Path(__file__).parent))

from app.services.excel_to_load_test_parser import ExcelLoadTestParser
from app.services.dynamic_locust_generator import DynamicLocustfileGenerator

def test_excel_parser():
    """Test Excel parsing functionality."""
    print("=" * 60)
    print("Testing Excel Parser")
    print("=" * 60)

    excel_file = "test_data/sample_load_test_apis.xlsx"

    if not Path(excel_file).exists():
        print(f"❌ Excel file not found: {excel_file}")
        return False

    try:
        parser = ExcelLoadTestParser()
        api_configs = parser.execute(excel_file)

        print(f"✅ Successfully parsed {len(api_configs)} API configurations\n")

        for i, api in enumerate(api_configs, 1):
            print(f"API #{i}: {api.name}")
            print(f"  Method: {api.method}")
            print(f"  URL: {api.base_url}{api.endpoint}")
            print(f"  Headers: {api.headers}")
            if api.payload:
                print(f"  Payload: {api.payload}")
            print(f"  Auth Type: {api.auth_config.auth_type.value}")
            print()

        return True

    except Exception as e:
        print(f"❌ Error parsing Excel: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_locustfile_generator():
    """Test Locustfile generation."""
    print("=" * 60)
    print("Testing Locustfile Generator")
    print("=" * 60)

    excel_file = "test_data/sample_load_test_apis.xlsx"

    try:
        # Parse Excel first
        parser = ExcelLoadTestParser()
        api_configs = parser.execute(excel_file)

        # Generate Locustfile for first API
        generator = DynamicLocustfileGenerator()
        output_path = "generated_locustfiles/test_locustfile.py"

        Path("generated_locustfiles").mkdir(exist_ok=True)

        locustfile_path = generator.generate_single_api(api_configs[0], output_path)

        print(f"✅ Generated Locustfile: {locustfile_path}\n")

        # Read and display generated file
        with open(locustfile_path, 'r') as f:
            content = f.read()

        print("Generated Locustfile content:")
        print("-" * 60)
        print(content[:500] + "..." if len(content) > 500 else content)
        print("-" * 60)

        # Validate syntax
        is_valid = generator.validate_locustfile(locustfile_path)
        if is_valid:
            print("✅ Locustfile syntax is valid")
        else:
            print("❌ Locustfile syntax is invalid")

        return is_valid

    except Exception as e:
        print(f"❌ Error generating Locustfile: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("LOAD TESTING BACKEND VERIFICATION")
    print("=" * 60 + "\n")

    results = []

    # Test 1: Excel Parser
    results.append(("Excel Parser", test_excel_parser()))

    print()

    # Test 2: Locustfile Generator
    results.append(("Locustfile Generator", test_locustfile_generator()))

    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)

    for test_name, passed in results:
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"{test_name}: {status}")

    all_passed = all(r[1] for r in results)

    print("\n" + "=" * 60)
    if all_passed:
        print("✅ ALL TESTS PASSED")
    else:
        print("❌ SOME TESTS FAILED")
    print("=" * 60 + "\n")

    return all_passed


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
