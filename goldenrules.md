# SREHubApp Developer Guide

## Core Development Principles


# Core Development Principles for SREHubApp (with Technical Implementation)

## 1. Minimal Data Handling
**Goal**: Fetch only the data you need. Process only what matters.

**Implementation**:
- **API Request Optimization**:  
  ```python
  url = "https://api.example.com/items?fields=id,name,status&limit=100"
  ```
- **Streaming Data**:
  ```python
  import requests
  with requests.get(url, stream=True) as r:
      for line in r.iter_lines():
          process(line)
  ```
- **Lazy Evaluation with Generators**:
  ```python
  def read_large_response():
      for item in api_response.json()["items"]:
          yield item
  ```

## 2. Efficient API Interactions
**Goal**: Optimize communication with external APIs.

**Implementation**:
- **Async HTTP using `httpx`**:
  ```python
  import httpx

  async def fetch(client, url):
      response = await client.get(url)
      return response.json()

  async with httpx.AsyncClient() as client:
      data = await fetch(client, 'https://api.example.com')
  ```
- **Retry with Exponential Backoff using `tenacity`**:
  ```python
  from tenacity import retry, wait_exponential, stop_after_attempt

  @retry(wait=wait_exponential(multiplier=1, min=4, max=10), stop=stop_after_attempt(5))
  def call_api():
      return requests.get('https://api.example.com')
  ```

## 3. Lightweight Processing
**Goal**: Write efficient algorithms and avoid heavy nested operations.

**Implementation**:
- **Optimize lookups with mapping**:
  ```python
  map_b = {b.id: b for b in list2}
  for a in list1:
      if a.id in map_b:
          pass
  ```
- **Vectorized operations with Pandas/Numpy (if needed)**.

## 4. Stateless and Modular Design
**Goal**: Keep modules independent and loosely coupled.

**Implementation**:
- **Connectors**:
  ```python
  class KubernetesConnector:
      def get_pods(self):
          pass
  ```
- **Processors**:
  ```python
  class PodProcessor:
      def find_failed_pods(self, pod_list):
          return [pod for pod in pod_list if pod.status == 'Failed']
  ```

## 5. Memory and Resource Optimization
**Goal**: Conserve memory and avoid unnecessary object retention.

**Implementation**:
- **Delete heavy objects after use**:
  ```python
  del large_object
  ```
- **Pipeline with Generators**:
  ```python
  def data_pipeline():
      for item in fetch_items():
          yield process_item(item)
  ```

## 6. Graceful Error Handling
**Goal**: Handle errors elegantly without crashing.

**Implementation**:
- **Exception Handling at Boundaries**:
  ```python
  try:
      response = requests.get(api_url)
      response.raise_for_status()
  except requests.HTTPError as e:
      logger.error(f"API Error: {e}")
      raise
  ```
- **Circuit Breaker using `pybreaker`**:
  ```python
  import pybreaker

  breaker = pybreaker.CircuitBreaker(fail_max=3, reset_timeout=60)

  @breaker
  def call_api():
      return requests.get('https://api.example.com')
  ```

## 7. Observability Built-in (Minimal Overhead)
**Goal**: Light observability without affecting performance.

**Implementation**:
- **Prometheus Metrics**:
  ```python
  from prometheus_client import Counter

  api_call_counter = Counter('api_calls_total', 'Total number of API calls')

  def make_call():
      api_call_counter.inc()
  ```
- **Structured Logging**:
  ```python
  import structlog

  logger = structlog.get_logger()
  logger.info("Fetching data", endpoint="api.example.com")
  ```

## 8. Parallelism and Concurrency
**Goal**: Execute tasks concurrently to improve speed.

**Implementation**:
- **Asyncio Parallel Calls**:
  ```python
  import asyncio
  import httpx

  async def fetch_url(url):
      async with httpx.AsyncClient() as client:
          return await client.get(url)

  async def main():
      urls = ['https://api1.com', 'https://api2.com']
      tasks = [fetch_url(url) for url in urls]
      results = await asyncio.gather(*tasks)

  asyncio.run(main())
  ```
- **ThreadPool for blocking IO**:
  ```python
  from concurrent.futures import ThreadPoolExecutor

  with ThreadPoolExecutor(max_workers=5) as executor:
      futures = [executor.submit(fetch_url, url) for url in urls]
  ```

## 9. Configuration over Hardcoding
**Goal**: No hardcoded values; everything must be configurable.

**Implementation**:
- **Environment Variables using `dotenv`**:
  ```python
  from dotenv import load_dotenv
  import os

  load_dotenv()
  API_KEY = os.getenv("API_KEY")
  ```
- **External Configuration Files (YAML)**:
  ```python
  import yaml

  with open('config.yaml') as f:
      config = yaml.safe_load(f)
  api_url = config['api']['url']
  ```

## 10. Early Performance Testing and Profiling
**Goal**: Measure performance early in the dev cycle.

**Implementation**:
- **Profiling with `cProfile`**:
  ```python
  import cProfile

  def main():
      pass  # your function

  cProfile.run('main()')
  ```
- **Benchmarking API Response Time**:
  ```python
  import time
  import httpx

  start = time.time()
  response = httpx.get('https://api.example.com')
  end = time.time()
  print(f"API Response Time: {end - start}s")
  ```
- **Memory Profiling**:
  ```python
  from memory_profiler import profile

  @profile
  def some_function():
      a = [1] * (10 ** 6)
      b = [2] * (2 * 10 ** 7)
      del b
      return a

  some_function()
  ```

# Summary of Key Tools and Libraries

| Purpose | Library/Tool |
|:---|:---|
| Async HTTP Calls | httpx, aiohttp |
| Retry Mechanisms | tenacity |
| Circuit Breaker | pybreaker |
| CPU & Memory Profiling | cProfile, memory_profiler |
| Observability/Metrics | prometheus_client |
| Structured Logging | structlog |
| Environment Configs | python-dotenv |
| Config Files | PyYAML |


---

## Developer's Golden Rules


# SREHubApp Developer's Golden Rules

> *Follow these simple rules to ensure every code, every feature, and every PR aligns with SREHubApp's performance-first development culture.*

## 1. Fetch Only What You Need
- Always request **only specific fields** and **minimal datasets** from external systems.

## 2. Always Think Async
- Use **async** or **parallelism** for all IO-heavy operations (API calls, DB queries).

## 3. Batch Whenever Possible
- Combine multiple small API requests into a **single batch** call wherever APIs allow.

## 4. Stream Big Data, Donât Load It
- If data is large, **stream** and **process iteratively**.  
Never load it fully into memory unless necessary.

## 5. Profile Before You Push
- Always run **performance profiling** (`cProfile`, response timing) before finalizing your PR.

## 6. Fail Fast, Retry Smart
- Implement **fail-fast** patterns.  
Use **exponential backoff retries** and **circuit breakers** for external API failures.

## 7. No Hardcoding, Only Config
- Everything configurable: URLs, limits, thresholds, credentials.

## 8. Metrics Are Mandatory
- Every important flow must have **basic observability hooks** (metrics counters, trace points).

## 9. Keep It Modular and Stateless
- Design in **small independent modules**.  
Avoid shared memory or state between components unless explicitly necessary.

## 10. Parallelize When Safe
- Analyze flows â if tasks are **independent**, run them **concurrently** using `asyncio` or thread pools.

# Quick Poster (Summary)

| Rule # | Golden Rule |
|:---|:---|
| 1 | Fetch Only What You Need |
| 2 | Always Think Async |
| 3 | Batch Whenever Possible |
| 4 | Stream Big Data, Donât Load It |
| 5 | Profile Before You Push |
| 6 | Fail Fast, Retry Smart |
| 7 | No Hardcoding, Only Config |
| 8 | Metrics Are Mandatory |
| 9 | Keep It Modular and Stateless |
| 10 | Parallelize When Safe |
