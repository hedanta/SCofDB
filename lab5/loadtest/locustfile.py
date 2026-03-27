"""
Locust template for LAB 05 RPS measurements.

Run:
locust -f loadtest/locustfile.py --host=http://localhost:8082
"""

from locust import HttpUser, task, between


class CacheUser(HttpUser):
    wait_time = between(0.1, 0.5)

    @task(3)
    def get_catalog_cached(self):
        self.client.get("/api/cache-demo/catalog?use_cache=true")
    
    @task(2)
    def get_catalog_not_cached(self):
        self.client.get("/api/cache-demo/catalog?use_cache=false")
