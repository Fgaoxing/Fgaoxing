import os
import requests
import time
from datetime import datetime
from collections import defaultdict
from typing import Dict, List

# Configuration
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
OUTPUT_FILE = "STARS.md"
CACHE_FILE = "stars_cache.json"
MAX_RETRIES = 3
REQUEST_INTERVAL = 1  # Seconds between requests

class StarOrganizer:
    def __init__(self):
        self.headers = {
            "Authorization": f"token {GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3+json"
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        self.cache = self._load_cache()

    def _load_cache(self) -> Dict:
        try:
            with open(CACHE_FILE, "r") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {"repos": {}, "etag": {}}

    def _save_cache(self):
        with open(CACHE_FILE, "w") as f:
            json.dump(self.cache, f)

    def _get_primary_language(self, owner: str, repo: str) -> str:
        """Get the most used language for a repository"""
        url = f"https://api.github.com/repos/{owner}/{repo}/languages"
        
        # ETag check for cache validation
        etag = self.cache["etag"].get(url)
        headers = self.headers.copy()
        if etag:
            headers["If-None-Match"] = etag

        for _ in range(MAX_RETRIES):
            try:
                response = self.session.get(url, headers=headers)
                if response.status_code == 304:
                    return self.cache["repos"][f"{owner}/{repo}"]["primary_lang"]
                
                if response.status_code == 200:
                    languages = response.json()
                    if not languages:
                        return "Others"
                    
                    primary_lang = max(languages, key=languages.get)
                    
                    # Update cache
                    self.cache["etag"][url] = response.headers.get("ETag", "")
                    self.cache["repos"][f"{owner}/{repo}"] = {
                        "primary_lang": primary_lang,
                        "timestamp": datetime.now().isoformat()
                    }
                    return primary_lang
                
                elif response.status_code == 404:
                    return "Archived/Deleted"
                
            except requests.exceptions.RequestException as e:
                print(f"Error getting languages for {owner}/{repo}: {e}")
                time.sleep(REQUEST_INTERVAL * 2)
        
        return "Unknown"

    def get_all_starred_repos(self) -> List[dict]:
        """Get all starred repositories with pagination"""
        url = "https://api.github.com/user/starred?per_page=100"
        repos = []
        
        while url:
            try:
                response = self.session.get(url)
                response.raise_for_status()
                repos.extend(response.json())
                
                # Check for rate limits
                remaining = int(response.headers.get("X-RateLimit-Remaining", 0))
                if remaining < 10:
                    reset_time = int(response.headers.get("X-RateLimit-Reset", 0))
                    sleep_time = max(reset_time - time.time(), 0) + 10
                    print(f"Rate limit approaching. Sleeping for {sleep_time} seconds")
                    time.sleep(sleep_time)
                
                url = response.links.get("next", {}).get("url")
                time.sleep(REQUEST_INTERVAL)
                
            except requests.exceptions.RequestException as e:
                print(f"Error fetching starred repos: {e}")
                break
        
        return repos

    def process_repos(self, repos: List[dict]) -> Dict[str, List[dict]]:
        """Process repositories and categorize by primary language"""
        categorized = defaultdict(list)
        
        for repo in repos:
            owner_login = repo["owner"]["login"]
            repo_name = repo["name"]
            repo_info = {
                "name": repo_name,
                "owner": owner_login,
                "url": repo["html_url"],
                "description": repo["description"] or "No description",
                "stars": repo["stargazers_count"],
                "archived": repo["archived"],
                "topics": repo.get("topics", []),
                "updated_at": repo["updated_at"]
            }
            
            # Get primary language
            cache_key = f"{owner_login}/{repo_name}"
            if cache_key in self.cache["repos"]:
                primary_lang = self.cache["repos"][cache_key]["primary_lang"]
            else:
                primary_lang = self._get_primary_language(owner_login, repo_name)
            
            # Handle special cases
            if repo["archived"]:
                category = "Archived"
            elif primary_lang == "Others":
                category = "Others"
            else:
                category = primary_lang
            
            repo_info["primary_lang"] = primary_lang
            categorized[category].append(repo_info)
            time.sleep(REQUEST_INTERVAL)
        
        return categorized

    def generate_report(self, categorized: Dict[str, List[dict]]) -> str:
        """Generate markdown report"""
        content = [
            "# GitHub Star Catalog\n",
            f"*Automatically generated at {datetime.now().strftime('%Y-%m-%d %H:%M')}*\n",
            "## Statistics\n",
            f"Total starred repositories: {sum(len(v) for v in categorized.values())}\n",
            f"Unique categories: {len(categorized)}\n\n",
            "## Categories\n"
        ]
        
        # Generate statistics
        lang_stats = sorted(
            [(lang, len(repos)) for lang, repos in categorized.items()],
            key=lambda x: (-x[1], x[0])
        )
        content.append("### Language Distribution\n")
        content.append("| Language | Count |\n|----------|-------|\n")
        for lang, count in lang_stats:
            content.append(f"| {lang} | {count} |\n")
        content.append("\n")
        
        # Generate sections
        for lang in sorted(categorized.keys(), key=lambda x: (-len(categorized[x]), x)):
            content.append(f"## {lang}\n")
            repos = sorted(categorized[lang], 
                         key=lambda x: (-x["stars"], x["name"]))
            
            for repo in repos:
                badges = []
                if repo["archived"]:
                    badges.append("🚧 Archived")
                if repo["topics"]:
                    badges.extend([f"`{topic}`" for topic in repo["topics"][:3]])
                
                star_count = f"★{repo['stars']:,}"
                description = repo["description"]
                
                content.append(
                    f"- [{repo['name']}]({repo['url']}) {star_count}\n"
                    f"  - {description}\n"
                    f"  - Last updated: {repo['updated_at'][:10]}  "
                    f"{' '.join(badges)}\n"
                )
        
        return "\n".join(content)

    def run(self):
        print("Fetching starred repositories...")
        repos = self.get_all_starred_repos()
        print(f"Found {len(repos)} starred repositories")
        
        print("Processing repositories...")
        categorized = self.process_repos(repos)
        
        print("Generating report...")
        report = self.generate_report(categorized)
        
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write(report)
        
        self._save_cache()
        print(f"Report generated at {OUTPUT_FILE}")

if __name__ == "__main__":
    organizer = StarOrganizer()
    organizer.run()
