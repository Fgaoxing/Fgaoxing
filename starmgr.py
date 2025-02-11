import os
import json
import requests
import time
from datetime import datetime
from collections import defaultdict
from typing import Dict, List, Tuple

# 配置项
GITHUB_TOKEN = os.getenv("GH_TOKEN")
OUTPUT_FILE = "STARS.md"
CACHE_FILE = "stars_cache.json"
REQUEST_INTERVAL = 1  # API请求间隔

class GitHubStarOrganizer:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"token {GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3+json"
        })
        self.cache = self.load_cache()
        self.stats = defaultdict(int)
        self.repo_count = 0

    def load_cache(self) -> Dict:
        try:
            with open(CACHE_FILE, "r") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {
                "languages": {},
                "categories": {},
                "etags": {},
                "last_updated": None
            }

    def save_cache(self):
        self.cache["last_updated"] = datetime.now().isoformat()
        with open(CACHE_FILE, "w") as f:
            json.dump(self.cache, f, indent=2)

    def get_github_category(self, repo: dict) -> Tuple[str, str]:
        """获取GitHub官方分类信息"""
        # 官方分类规则
        if repo["archived"]:
            return "Archived", "🚧 Archived repositories"
        if repo["fork"]:
            return "Forks", "🍴 Forked repositories"
        if "template" in repo["topics"]:
            return "Templates", "📋 Repository templates"
        
        # 检测官方主题分类
        official_topics = {
            "android": "📱 Android",
            "ios": " iOS",
            "react": "⚛️ React",
            "vue": "🖖 Vue.js",
            "machine-learning": "🤖 ML/AI"
        }
        for topic in repo["topics"]:
            if topic in official_topics:
                return official_topics[topic], "GitHub官方主题分类"
        
        # 使用GitHub检测的主要语言
        lang_data = self.get_primary_language(repo["owner"]["login"], repo["name"])
        return lang_data

    def get_primary_language(self, owner: str, repo: str) -> Tuple[str, str]:
        """获取仓库主要语言及分类"""
        cache_key = f"{owner}/{repo}"
        if cache_key in self.cache["languages"]:
            return self.cache["languages"][cache_key]["category"], "自动语言分类"

        try:
            response = self.session.get(f"https://api.github.com/repos/{owner}/{repo}/languages")
            if response.status_code == 200:
                languages = response.json()
                if not languages:
                    return "Others", "🗂️ Other languages"
                
                primary_lang = max(languages.keys(), key=lambda k: languages[k])
                lang_category = self.map_language_category(primary_lang)
                
                # 缓存结果
                self.cache["languages"][cache_key] = {
                    "primary_lang": primary_lang,
                    "category": lang_category,
                    "timestamp": datetime.now().isoformat()
                }
                return lang_category, "GitHub官方语言分类"
            
            return "Unknown", "❓ Unknown category"
        except Exception as e:
            print(f"Error getting language: {str(e)}")
            return "Unknown", "❓ Unknown category"

    def map_language_category(self, lang: str) -> str:
        """映射到GitHub官方语言分类"""
        categories = {
            "Python": "🐍 Python",
            "JavaScript": "🌐 JavaScript",
            "TypeScript": "📘 TypeScript",
            "Java": "☕ Java",
            "C++": "🖥️ C/C++",
            "C": "🖥️ C/C++",
            "Go": "🐹 Go",
            "Rust": "🦀 Rust",
            "Ruby": "💎 Ruby",
            "PHP": "🐘 PHP",
            "Swift": "🍎 Swift",
            "Kotlin": "🅚 Kotlin"
        }
        return categories.get(lang, f"📚 {lang}")

    def fetch_all_starred(self) -> List[dict]:
        """获取所有star的仓库"""
        repos = []
        page = 1
        while True:
            url = f"https://api.github.com/user/starred?per_page=100&page={page}"
            try:
                response = self.session.get(url)
                response.raise_for_status()
                batch = response.json()
                if not batch:
                    break
                
                repos.extend(batch)
                page += 1
                self.repo_count += len(batch)

                # 处理速率限制
                remaining = int(response.headers.get("X-RateLimit-Remaining", 1))
                if remaining < 5:
                    reset_time = int(response.headers.get("X-RateLimit-Reset", time.time() + 3600))
                    sleep_time = max(reset_time - time.time() + 10, 0)
                    print(f"Rate limit reached. Sleeping {sleep_time} seconds")
                    time.sleep(sleep_time)
                
                time.sleep(REQUEST_INTERVAL)

            except Exception as e:
                print(f"Error fetching stars: {str(e)}")
                break
        return repos

    def process_repos(self, repos: List[dict]) -> Dict[str, List]:
        """处理仓库数据"""
        categorized = defaultdict(lambda: defaultdict(list))
        for repo in repos:
            # 获取分类信息
            category, reason = self.get_github_category(repo)
            sub_category = reason  # 使用分类原因作为子类
            
            repo_data = {
                "name": repo["name"],
                "owner": repo["owner"]["login"],
                "url": repo["html_url"],
                "desc": repo["description"] or "No description",
                "stars": repo["stargazers_count"],
                "topics": repo.get("topics", []),
                "updated": repo["pushed_at"][:10],
                "created": repo["created_at"][:10],
                "archived": repo["archived"],
                "fork": repo["fork"],
                "license": repo["license"]["key"] if repo["license"] else None,
                "category_reason": reason
            }

            categorized[category][sub_category].append(repo_data)
            self.stats[category] += 1
        
        return categorized

    def generate_markdown(self, categories: Dict) -> str:
        """生成Markdown报告"""
        content = [
            "# GitHub Star Catalog\n",
            f"*Last Updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*\n\n",
            "## 🌟 Statistics\n",
            f"Total Starred Repositories: {self.repo_count}\n",
            "### Category Distribution\n",
            "| Category | Count |\n|----------|------:|\n"
        ]

        # 生成统计
        for cat, count in sorted(self.stats.items(), key=lambda x: (-x[1], x[0])):
            content.append(f"| {cat} | {count} |")
        content.append("\n")

        # 生成分类内容
        for main_cat in sorted(categories.keys(), key=lambda x: (-self.stats[x], x)):
            content.append(f"## {main_cat}\n")
            
            for sub_cat in categories[main_cat]:
                content.append(f"### {sub_cat}\n")
                
                repos = sorted(categories[main_cat][sub_cat], 
                              key=lambda x: (-x["stars"], x["name"]))
                
                for repo in repos:
                    badges = []
                    if repo["archived"]:
                        badges.append("![Archived](https://img.shields.io/badge/-Archived-red)")
                    if repo["license"]:
                        badges.append(f"![License](https://img.shields.io/badge/license-{repo['license']}-blue)")
                    if repo["topics"]:
                        badges.extend([f"`{t}`" for t in repo["topics"][:3]])
                    
                    content.append(
                        f"- [{repo['name']}]({repo['url']}) ★{repo['stars']}\n"
                        f"  - {repo['desc']}\n"
                        f"  - Created: {repo['created']}  "
                        f"Updated: {repo['updated']}  "
                        f"{' '.join(badges)}\n"
                    )
                
                content.append("\n")
        
        return "\n".join(content)

    def run(self):
        print("🚀 Starting GitHub Star Organizer...")
        repos = self.fetch_all_starred()
        print(f"🔍 Processing {len(repos)} repositories...")
        categorized = self.process_repos(repos)
        report = self.generate_markdown(categorized)
        
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write(report)
        
        self.save_cache()
        print("✅ Report generated at STARS.md")

if __name__ == "__main__":
    GitHubStarOrganizer().run()
