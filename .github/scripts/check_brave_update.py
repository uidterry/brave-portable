#!/usr/bin/env python3
import os
import re
import subprocess
from datetime import datetime

import requests
from packaging import version

CHANGELOG_URL = "https://raw.githubusercontent.com/brave/brave-browser/master/CHANGELOG_DESKTOP.md"
REQUEST_TIMEOUT = 30


def get_latest_brave_version():
    """获取 Brave 官方 CHANGELOG 中的最新版本。"""
    response = requests.get(CHANGELOG_URL, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()

    pattern = r"## \[([\d.]+)\]\(https://github\.com/brave/brave-browser/releases/tag/v[\d.]+\)"
    matches = re.findall(pattern, response.text)
    if not matches:
        raise RuntimeError("无法在 Brave CHANGELOG 中找到版本号")
    return matches[0]


def compare_versions(version1, version2):
    """version1 比 version2 新时返回 True。"""
    return version.parse(version1) > version.parse(version2)


def read_current_release():
    """从 build.properties 读取当前版本和发行号。"""
    with open("build.properties", "r", encoding="utf-8") as file:
        content = file.read()

    version_match = re.search(r"^app\.version\s*=\s*([\d.]+)$", content, re.MULTILINE)
    release_match = re.search(r"^app\.release\s*=\s*(\d+)$", content, re.MULTILINE)
    if not version_match or not release_match:
        raise RuntimeError("build.properties 缺少有效的 app.version 或 app.release")
    return version_match.group(1), int(release_match.group(1))


def update_build_properties(new_version):
    """更新版本号并递增发行号。"""
    with open("build.properties", "r", encoding="utf-8") as file:
        content = file.read()

    _, current_release = read_current_release()
    new_release = current_release + 1
    content = re.sub(
        r"^app\.version\s*=\s*[\d.]+$",
        f"app.version = {new_version}",
        content,
        flags=re.MULTILINE,
    )
    content = re.sub(
        r"^app\.release\s*=\s*\d+$",
        f"app.release = {new_release}",
        content,
        flags=re.MULTILINE,
    )

    with open("build.properties", "w", encoding="utf-8") as file:
        file.write(content)
    return new_release


def update_changelog(new_version, new_release):
    """在 CHANGELOG 顶部记录新版本。"""
    with open("CHANGELOG.md", "r", encoding="utf-8") as file:
        content = file.read()

    today = datetime.now().strftime("%Y/%m/%d")
    new_entry = f"## {new_version}-{new_release} ({today})\n\n* Brave {new_version}\n\n"
    updated_content, count = re.subn(
        r"# Changelog\n\n",
        f"# Changelog\n\n{new_entry}",
        content,
        count=1,
    )
    if count != 1:
        raise RuntimeError("CHANGELOG.md 缺少预期标题")

    with open("CHANGELOG.md", "w", encoding="utf-8") as file:
        file.write(updated_content)


def set_output(name, value):
    """设置 GitHub Actions 输出变量。"""
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        return
    with open(output_path, "a", encoding="utf-8") as file:
        file.write(f"{name}={value}\n")


def run_git(*args):
    """执行 Git 命令，失败时立即终止工作流。"""
    return subprocess.run(
        ["git", *args],
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()


def repository_path():
    """获取 owner/repo 格式的仓库路径。"""
    repo_path = os.environ.get("GITHUB_REPOSITORY")
    if not repo_path:
        remote_url = run_git("config", "--get", "remote.origin.url")
        match = re.search(r"github\.com[:/](.+)$", remote_url)
        if not match:
            raise RuntimeError(f"无法解析 GitHub 远程地址: {remote_url}")
        repo_path = match.group(1).removesuffix(".git")

    if repo_path.count("/") != 1:
        raise RuntimeError(f"无效的 GitHub 仓库路径: {repo_path}")
    return repo_path


def ensure_tag(app_version, release, require_current_sha=False):
    """确保对应标签存在；新版本可额外校验标签必须指向当前提交。"""
    token = os.environ.get("REPO_ACCESS_TOKEN")
    if not token:
        raise RuntimeError("缺少 REPO_ACCESS_TOKEN，无法创建能触发构建的标签")

    tag_name = f"v{app_version}-{release}"
    current_sha = run_git("rev-parse", "HEAD")
    api_url = f"https://api.github.com/repos/{repository_path()}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    response = requests.get(
        f"{api_url}/git/ref/tags/{tag_name}",
        headers=headers,
        timeout=REQUEST_TIMEOUT,
    )
    if response.status_code == 200:
        tagged_sha = response.json()["object"]["sha"]
        if require_current_sha and tagged_sha != current_sha:
            raise RuntimeError(
                f"标签 {tag_name} 已指向 {tagged_sha}，不等于当前提交 {current_sha}"
            )
        print(f"标签已存在: {tag_name} ({tagged_sha})")
        return False
    if response.status_code != 404:
        response.raise_for_status()

    response = requests.post(
        f"{api_url}/git/refs",
        headers=headers,
        json={"ref": f"refs/tags/{tag_name}", "sha": current_sha},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    print(f"已创建标签: {tag_name}")
    return True


def publish_outputs(app_version, release):
    tag_name = f"v{app_version}-{release}"
    set_output("updated", "true")
    set_output("version", app_version)
    set_output("tag", tag_name)
    print(f"标签 {tag_name} 已触发构建流程")


def main():
    latest_version = get_latest_brave_version()
    current_version, current_release = read_current_release()
    print(f"最新 Brave 版本: {latest_version}")
    print(f"当前版本: {current_version}-{current_release}")

    if latest_version == current_version:
        if ensure_tag(current_version, current_release):
            publish_outputs(current_version, current_release)
        else:
            print("版本和标签均已是最新状态")
            set_output("updated", "false")
        return

    if not compare_versions(latest_version, current_version):
        print(f"检测到 {latest_version}，它不比当前版本 {current_version} 更新")
        set_output("updated", "false")
        return

    print(f"发现新版本: {current_version} -> {latest_version}")
    new_release = update_build_properties(latest_version)
    update_changelog(latest_version, new_release)

    run_git("config", "user.name", "GitHub Actions Bot")
    run_git("config", "user.email", "actions@github.com")
    run_git("add", "build.properties", "CHANGELOG.md")
    run_git("commit", "-m", f"Update Brave to {latest_version}")
    run_git("push", "origin", "HEAD")

    ensure_tag(latest_version, new_release, require_current_sha=True)
    publish_outputs(latest_version, new_release)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        set_output("updated", "false")
        raise
