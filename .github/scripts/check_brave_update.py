#!/usr/bin/env python3
import os
import re
import sys
import requests
from datetime import datetime
from packaging import version

def get_latest_brave_version():
    """获取Brave官方CHANGELOG中的最新版本"""
    changelog_url = "https://raw.githubusercontent.com/brave/brave-browser/master/CHANGELOG_DESKTOP.md"
    response = requests.get(changelog_url)
    if response.status_code != 200:
        print(f"获取Brave CHANGELOG失败: {response.status_code}")
        return None
    
    # 寻找版本号 - 使用更准确的正则表达式匹配CHANGELOG格式
    # 示例: ## [1.76.81](https://github.com/brave/brave-browser/releases/tag/v1.76.81)
    version_pattern = r'## \[([\d\.]+)\]\(https:\/\/github\.com\/brave\/brave-browser\/releases\/tag\/v[\d\.]+\)'
    matches = re.findall(version_pattern, response.text)
    
    if not matches:
        print("无法在CHANGELOG中找到版本号")
        return None
    
    # 返回找到的第一个版本号（最新版本）
    return matches[0]

def compare_versions(version1, version2):
    """比较两个版本号，如果version1比version2新，返回True"""
    return version.parse(version1) > version.parse(version2)

def get_current_brave_version():
    """从build.properties获取当前版本"""
    with open('build.properties', 'r') as f:
        content = f.read()
    
    version_match = re.search(r'app\.version = ([\d\.]+)', content)
    if not version_match:
        print("无法在build.properties中找到版本号")
        return None
    
    return version_match.group(1)

def update_build_properties(new_version):
    """更新build.properties中的版本号"""
    with open('build.properties', 'r') as f:
        content = f.read()
    
    # 更新版本号
    updated_content = re.sub(r'app\.version = [\d\.]+', f'app.version = {new_version}', content)
    
    # 增加release号
    release_match = re.search(r'app\.release = (\d+)', updated_content)
    if release_match:
        current_release = int(release_match.group(1))
        new_release = current_release + 1
        updated_content = re.sub(r'app\.release = \d+', f'app.release = {new_release}', updated_content)
    
    with open('build.properties', 'w') as f:
        f.write(updated_content)
    
    return new_release if release_match else None

def update_changelog(new_version, new_release):
    """更新CHANGELOG.md文件"""
    with open('CHANGELOG.md', 'r') as f:
        content = f.read()
    
    # 获取当前日期作为发布日期
    today = datetime.now().strftime("%Y/%m/%d")
    
    # 准备新的变更记录条目
    new_entry = f"## {new_version}-{new_release} ({today})\n\n* Brave {new_version}\n\n"
    
    # 在文件头部添加新条目 (在# Changelog 之后)
    updated_content = re.sub(r'# Changelog\n\n', f'# Changelog\n\n{new_entry}', content)
    
    with open('CHANGELOG.md', 'w') as f:
        f.write(updated_content)

def set_output(name, value):
    """设置GitHub Actions输出变量"""
    # GitHub Actions 新的输出语法
    with open(os.environ.get("GITHUB_OUTPUT", ""), "a") as f:
        f.write(f"{name}={value}\n")

def create_and_push_tag(version, release):
    """创建并推送版本标签"""
    tag_name = f"{version}-{release}"
    
    # 配置Git
    os.system('git config --global user.name "GitHub Actions Bot"')
    os.system('git config --global user.email "actions@github.com"')
    
    # 获取仓库所有者和名称
    remote_url = os.popen('git config --get remote.origin.url').read().strip()
    repo_path = re.search(r'github\.com[:/](.+)(?:\.git)?$', remote_url).group(1)
    
    # 创建本地标签
    print(f"创建标签: {tag_name}")
    os.system(f'git tag {tag_name}')
    
    # 使用PAT推送标签 - 这样可以触发其他工作流
    github_token = os.environ.get('REPO_ACCESS_TOKEN')
    if github_token:
        # 使用带令牌的URL进行推送
        token_url = f'https://x-access-token:{github_token}@github.com/{repo_path}'
        print("使用PAT推送标签")
        result = os.system(f'git push {token_url} {tag_name}')
    else:
        # 如果没有令牌，使用常规方式推送
        print("没有找到PAT，使用常规方式推送标签")
        result = os.system(f'git push origin {tag_name}')
    
    if result != 0:
        print(f"推送标签 {tag_name} 失败")
        return False
    
    print(f"成功创建并推送标签: {tag_name}")
    return True

def main():
    # 获取最新的Brave版本和当前版本
    latest_version = get_latest_brave_version()
    current_version = get_current_brave_version()
    
    if not latest_version or not current_version:
        set_output("updated", "false")
        sys.exit(0)
    
    print(f"最新Brave版本: {latest_version}")
    print(f"当前版本: {current_version}")
    
    # 比较版本
    if latest_version == current_version:
        print("已经是最新版本")
        set_output("updated", "false")
        return
    
    if not compare_versions(latest_version, current_version):
        print(f"检测到版本 {latest_version}，但它不比当前版本 {current_version} 更新")
        set_output("updated", "false")
        return
    
    # 更新文件
    print(f"发现新版本! 更新从 {current_version} 到 {latest_version}")
    new_release = update_build_properties(latest_version)
    update_changelog(latest_version, new_release)
    
    # 提交更改
    os.system('git config --global user.name "GitHub Actions Bot"')
    os.system('git config --global user.email "actions@github.com"')
    os.system('git add build.properties CHANGELOG.md')
    os.system(f'git commit -m "Update Brave to {latest_version}"')
    push_result = os.system('git push')
    
    if push_result != 0:
        print("提交更改失败")
        set_output("updated", "false")
        return
    
    # 创建并推送标签
    tag_result = create_and_push_tag(latest_version, new_release)
    
    # 设置输出
    if tag_result:
        set_output("updated", "true")
        set_output("version", latest_version)
        set_output("tag", f"{latest_version}-{new_release}")
    else:
        set_output("updated", "false")

if __name__ == "__main__":
    main() 