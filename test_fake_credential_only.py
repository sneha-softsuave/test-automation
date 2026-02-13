"""
Test Locustfile - ONLY uses fake credential to verify 401 detection.

This file tests ONLY the fake@gmail.com credential to verify that:
1. The API returns 401
2. Locust correctly detects it as a failure

Expected Result: 100% failure rate
"""

from locust import HttpUser, task, between

class FakeCredentialTest(HttpUser):
    """Test with fake credential only"""

    host = "https://dev-emergex.zapptor.com/"
    wait_time = between(1, 2)

    def on_start(self):
        """Initialize headers"""
        self.headers = {"Content-Type": "application/json"}
        print(f"\n[INIT] User {id(self)} started - will use FAKE credential")

    @task
    def test_fake_login(self):
        """Test login with fake@gmail.com (should fail with 401)"""

        payload = {
            "email": "fake@gmail.com",
            "password": "123456",
            "rememberMe": False
        }

        print(f"[REQUEST] User {id(self)} attempting login with: {payload['email']}")

        with self.client.post(
            "api/auth/login",
            json=payload,
            headers=self.headers,
            catch_response=True,
            name="POST api/auth/login (FAKE)"
        ) as response:
            # Log response details
            print(f"[RESPONSE] Status Code: {response.status_code}")
            print(f"[RESPONSE] Content: {response.text[:150]}")

            # Validate response
            if response.status_code == 401:
                # This is EXPECTED - fake credential should fail
                print(f"[FAILURE] ✅ Correctly detected fake credential (401)")
                response.failure(f"Authentication failed as expected: {response.text[:50]}")
            elif response.status_code in [200, 201]:
                # This is UNEXPECTED - fake credential should NOT succeed!
                print(f"[ERROR] ❌ Fake credential returned 200! This is wrong!")
                response.failure(f"Fake credential should NOT succeed! Got 200")
            else:
                # Unexpected status code
                print(f"[ERROR] ❌ Unexpected status code: {response.status_code}")
                response.failure(f"Unexpected status: {response.status_code}")


if __name__ == "__main__":
    import os
    print("\n" + "="*80)
    print("🧪 FAKE CREDENTIAL TEST")
    print("="*80)
    print("This test uses ONLY fake@gmail.com to verify 401 detection")
    print("Expected: 100% failure rate (all requests should fail with 401)")
    print("="*80 + "\n")
    print("Run with:")
    print("  locust -f test_fake_credential_only.py --headless -u 10 -r 2 -t 30s")
    print("\nOr with web UI:")
    print("  locust -f test_fake_credential_only.py")
    print("\n" + "="*80)
