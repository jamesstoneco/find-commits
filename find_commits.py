#!/usr/bin/env python3

import click
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.prompt import Confirm
from git import Repo, GitCommandError
from datetime import datetime, timedelta
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from collections import defaultdict

# Initialize rich console
console = Console()

SEARCH_DIRS = [
    "/Users/james/code",
    "/Users/james/projects"
]

def find_git_repos(base_dirs):
    """Find all git repositories in the given base directories."""
    repos = []
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Scanning for repositories...", total=None)
        for base_dir in base_dirs:
            for root, dirs, _ in os.walk(base_dir):
                if '.git' in dirs:
                    repos.append(root)
                    progress.update(task, description=f"Found: {Path(root).name}")
    return repos

def search_commits(repo_path, date, author):
    """Search for commits in a specific repository on a specific date."""
    try:
        repo = Repo(repo_path)
        since = date.replace(hour=0, minute=0, second=0, microsecond=0)
        until = date.replace(hour=23, minute=59, second=59, microsecond=999999)
        
        commits = list(repo.iter_commits(
            all=True,
            author=author,
            since=since,
            until=until
        ))
        
        if commits:
            return Path(repo_path).name, commits
        return None
    except GitCommandError:
        return None

def format_commit(commit):
    """Format a commit for display."""
    short_hash = commit.hexsha[:7]
    date = datetime.fromtimestamp(commit.committed_date)
    return f"[dim]{short_hash}[/dim] {commit.summary}"

@click.command()
@click.option('--date', '-d', default=None, help='Date to search (YYYY-MM-DD)')
@click.option('--author', '-a', default="your-name@users.noreply.github.com", help='Author email')
def main(date, author):
    """Search for commits across multiple repositories."""
    search_date = datetime.strptime(date, "%Y-%m-%d") if date else datetime.now()
    
    # Find all repositories
    repos = find_git_repos(SEARCH_DIRS)
    console.print(f"\nFound [bold]{len(repos)}[/] repositories to search")
    
    # Search for commits
    results = defaultdict(list)
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Searching repositories...", total=len(repos))
        
        with ThreadPoolExecutor() as executor:
            futures = []
            for repo_path in repos:
                future = executor.submit(search_commits, repo_path, search_date, author)
                futures.append(future)
            
            for future in futures:
                result = future.result()
                if result:
                    repo_name, commits = result
                    results[repo_name].extend(commits)
                progress.advance(task)
    
    # Display results
    if not results:
        console.print("\n[yellow]No commits found for this date.[/]")
        if Confirm.ask("Would you like to expand the search to adjacent days?"):
            # Expand search to adjacent days
            adjacent_dates = [
                search_date - timedelta(days=1),
                search_date + timedelta(days=1)
            ]
            console.print("\n[bold]Searching adjacent days...[/]")
            
            for adj_date in adjacent_dates:
                with Progress(
                    SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    console=console,
                ) as progress:
                    task = progress.add_task(f"Searching {adj_date.date()}...", total=len(repos))
                    
                    with ThreadPoolExecutor() as executor:
                        futures = []
                        for repo_path in repos:
                            future = executor.submit(search_commits, repo_path, adj_date, author)
                            futures.append(future)
                        
                        for future in futures:
                            result = future.result()
                            if result:
                                repo_name, commits = result
                                if commits:
                                    console.print(f"\n[bold blue]{adj_date.date()}[/] - [bold]{repo_name}[/]")
                                    for commit in sorted(commits, key=lambda x: x.committed_date, reverse=True):
                                        console.print(f"  {format_commit(commit)}")
                            progress.advance(task)
    else:
        console.print(f"\n[bold green]Found commits on {search_date.date()}:[/]")
        for repo_name, commits in results.items():
            console.print(f"\n[bold]{repo_name}[/]")
            for commit in sorted(commits, key=lambda x: x.committed_date, reverse=True):
                console.print(f"  {format_commit(commit)}")

if __name__ == '__main__':
    main() 