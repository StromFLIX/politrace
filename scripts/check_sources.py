"""Read-only diagnostics for runner-specific access to the official BGBl endpoints.

No credentials, alternative proxies or model calls. Only status/content metadata is logged.
A successful diagnostic job is not a successful ingestion; inspect each endpoint's status.
"""
import json
from datetime import date
from urllib.parse import urlencode

import httpx

from pipeline.archive import SEARCH_URL


def main():
    query = urlencode({"lastChangeVdAfter": "2025-03-25", "lastChangeVdBefore": date.today().isoformat(),
                       "cl2Metadaten_cl2Categories_Typ": "gesetz", "resultsPerPage": "100",
                       "sortOrder": "dateOfIssue_dt asc"})
    endpoints = {
        "home": "https://www.recht.bund.de/",
        "archive": SEARCH_URL + "?" + query,
        "rss": "https://www.recht.bund.de/rss/feeds/rss_bgbl-1.xml",
        "law": "https://www.recht.bund.de/bgbl/1/2026/285/VO.html",
        "pdf": "https://www.recht.bund.de/bgbl/1/2026/285/regelungstext.pdf?__blob=publicationFile&v=2",
        "apex_home": "https://recht.bund.de/",
    }
    results = []
    with httpx.Client(timeout=30, headers={"User-Agent": "Politrace/0.1"}) as client:
        for name, url in endpoints.items():
            try:
                response = client.get(url)
                results.append({"endpoint": name, "status": response.status_code,
                                "content_type": response.headers.get("content-type"),
                                "bytes": len(response.content),
                                "server": response.headers.get("server")})
            except httpx.TransportError as error:
                results.append({"endpoint": name, "error_type": type(error).__name__})
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
