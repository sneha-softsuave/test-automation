from locust import HttpUser, task, between

class HealthCheckUser(HttpUser):
    # Simulates human wait time between requests
    wait_time = between(5, 10)

    # @task
    # def health_check(self):
    #     self.client.get("/api/v1/health")

    @task
    def upload_excel(self):
        file_path = "/home/admin1/project - POCs/test-automation-project/test-automation/test_data/Emergex Automation Test Cases updated with inputs.xlsx"

        with open(file_path, "rb") as f:
            files = {
                "file": (
                    "Emergex Automation Test Cases updated with inputs.xlsx",
                    f,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
            }

            response = self.client.post(
                "/api/v1/upload-excel",
                files=files
            )

            # Optional safety check
            if response.status_code != 200:
                response.failure(f"Upload failed: {response.status_code}")



    @task
    def get_request(self):
        self.client.get("/get")
