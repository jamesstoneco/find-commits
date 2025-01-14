#!/usr/bin/env python3

import click
from rich.console import Console
from rich.progress import Progress, TextColumn, BarColumn, TimeElapsedColumn
from rich.table import Table
from git import Repo, GitCommandError
from datetime import datetime, timedelta
import os
from pathlib import Path
from collections import defaultdict
import sys
import time
import statistics
import signal
from rich.prompt import Prompt

# Initialize rich console
console = Console()

# Default search directories
DEFAULT_SEARCH_DIRS = [
    "~/code",
    "~/projects"
]

class SearchCancelled(Exception):
    """Custom exception for search cancellation."""
    pass

def find_git_repos(base_dirs, stats, verbose=False):
    """Find all git repositories in the given base directories."""
    repos = []
    
    # Common directories to skip for better performance
    SKIP_DIRS = {
        'node_modules',
        'vendor',
        'tmp',
        'temp',
        'dist',
        'build',
        'target',
        'venv',
        '.venv',
        '.env',
        '__pycache__',
        '.next',
        '.cache',
        'coverage',
        'logs'
    }
    
    progress = Progress(
        TextColumn("[bold blue]{task.description}"),
        BarColumn(bar_width=40),
        TextColumn("•"),
        TimeElapsedColumn(),
        console=console,
        expand=True,
        transient=True
    )
    
    with progress:
        task = progress.add_task("Discovering repositories", total=None)
        
        try:
            for base_dir in base_dirs:
                base_dir = os.path.expanduser(base_dir)
                if not os.path.exists(base_dir):
                    if verbose:
                        console.print(f"[yellow]Warning: Directory {base_dir} does not exist[/]")
                    continue
                
                for root, dirs, _ in os.walk(base_dir, topdown=True):
                    stats.total_dirs_scanned += 1
                    
                    # Check if this is a git repository
                    if os.path.isdir(os.path.join(root, '.git')):
                        stats.total_git_dirs_found += 1
                        try:
                            repo = Repo(root)
                            if not repo.bare:
                                repos.append(root)
                                if verbose:
                                    progress.update(task, description=f"Found: {Path(root).name}")
                            else:
                                stats.bare_repos += 1
                                if verbose:
                                    console.print(f"[yellow]Skipping bare repository: {root}[/]")
                        except Exception as e:
                            stats.invalid_git_dirs += 1
                            if verbose:
                                console.print(f"[yellow]Warning: Invalid repository at {root}: {str(e)}[/]")
                            continue
                    
                    # Skip certain directories for performance
                    original_dirs = set(dirs)
                    dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
                    stats.total_dirs_skipped += len(original_dirs) - len(dirs)
        
        except KeyboardInterrupt:
            raise SearchCancelled
    
    if verbose and repos:
        console.print(f"\n[green]✓[/] Found [bold]{len(repos)}[/] repositories:")
        for repo in sorted(repos):
            console.print(f"  [dim]•[/] {repo}")
    
    return repos

def get_repo_branches(repo_path):
    """Get list of branches in a repository."""
    try:
        repo = Repo(repo_path)
        branches = []
        try:
            branches.extend([ref.name for ref in repo.refs if not ref.name.endswith('/HEAD')])
        except:
            pass
        
        if not branches:
            common_branches = ['main', 'master', 'dev', 'development']
            for branch in common_branches:
                try:
                    if branch in repo.refs:
                        branches.append(branch)
                except:
                    continue
        
        return branches
    except:
        return []

def search_commits_in_repo(repo_path, date, author, verbose=False):
    """Search for commits in a specific repository on a specific date."""
    try:
        repo = Repo(repo_path)
        since = date.replace(hour=0, minute=0, second=0, microsecond=0)
        until = date.replace(hour=23, minute=59, second=59, microsecond=999999)
        
        # Check repository size
        try:
            # Get size of .git directory
            git_size = sum(
                os.path.getsize(os.path.join(dirpath, filename))
                for dirpath, _, filenames in os.walk(os.path.join(repo_path, '.git'))
                for filename in filenames
            ) / (1024 * 1024)  # Convert to MB
            
            if git_size > 500:  # If repo is larger than 500MB
                if verbose:
                    console.print(f"[yellow]Warning: Large repository ({git_size:.0f}MB): {repo_path}[/]")
        except:
            pass
        
        all_commits = []
        branches = get_repo_branches(repo_path)
        
        if not branches:
            return None
        
        # Use a more efficient search strategy for large repos
        try:
            # Try searching all branches at once first
            commits = list(repo.iter_commits(
                all=True,
                author=author,
                since=since,
                until=until,
                max_count=100  # Limit number of commits to search
            ))
            all_commits.extend(commits)
        except:
            # Fallback to searching each branch individually
            for branch in branches:
                try:
                    commits = list(repo.iter_commits(
                        branch,
                        author=author,
                        since=since,
                        until=until,
                        max_count=50  # Limit per branch
                    ))
                    all_commits.extend(commits)
                except:
                    continue
        
        unique_commits = list({commit.hexsha: commit for commit in all_commits}.values())
        
        if unique_commits:
            return Path(repo_path).name, unique_commits
        return None
    except Exception as e:
        return None

def format_commit(commit, is_new=False):
    """Format a commit for display."""
    short_hash = commit.hexsha[:7]
    new_tag = "[bold green]NEW[/] " if is_new else ""
    # Wrap long commit messages while preserving formatting
    summary = commit.summary
    if len(summary) > 80:
        summary = summary[:77] + "..."
    return f"    {new_tag}{summary} [dim]({short_hash})[/]"

class SearchStats:
    def __init__(self):
        self.start_time = time.time()
        self.repo_search_times = []
        self.total_dirs_scanned = 0
        self.total_dirs_skipped = 0
        self.total_git_dirs_found = 0
        self.invalid_git_dirs = 0
        self.bare_repos = 0
        
    def display(self):
        total_time = time.time() - self.start_time
        
        table = Table(title="Search Statistics")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green", justify="right")
        
        table.add_row("Total time", f"{total_time:.2f}s")
        table.add_row("Directories scanned", str(self.total_dirs_scanned))
        table.add_row("Directories skipped", str(self.total_dirs_skipped))
        table.add_row("Git directories found", str(self.total_git_dirs_found))
        table.add_row("Invalid git repos", str(self.invalid_git_dirs))
        table.add_row("Bare repositories", str(self.bare_repos))
        
        if self.repo_search_times:
            table.add_row("Average search time", f"{statistics.mean(self.repo_search_times):.2f}s")
            table.add_row("Fastest search", f"{min(self.repo_search_times):.2f}s")
            table.add_row("Slowest search", f"{max(self.repo_search_times):.2f}s")
        
        console.print("\n")
        console.print(table)

def display_commits_by_date(results, seen_commits=None):
    """Display commits grouped by repository and date."""
    # First, reorganize commits by repo and date
    organized = defaultdict(lambda: defaultdict(list))
    total_commits = 0
    
    if seen_commits is None:
        seen_commits = set()
    
    for repo_name, commits in results.items():
        for commit in commits:
            commit_date = datetime.fromtimestamp(commit.committed_date)
            organized[repo_name][commit_date.date()].append(commit)
            total_commits += 1
    
    # Display organized results
    total_repos = len(organized)
    console.print(f"\n[bold green]Found {total_commits} commit{'s' if total_commits > 1 else ''} "
                 f"across {total_repos} repositor{'ies' if total_repos > 1 else 'y'}:[/]")
    
    for repo_name, dates in organized.items():
        console.print(f"\n[bold blue]{repo_name}[/]")
        for date, commits in sorted(dates.items()):
            console.print(f"  [yellow]{date.strftime('%d/%m')}[/] ([green]{len(commits)} commit{'s' if len(commits) > 1 else ''}[/])")
            for commit in sorted(commits, key=lambda x: x.committed_date, reverse=True):
                is_new = commit.hexsha not in seen_commits
                if is_new:
                    seen_commits.add(commit.hexsha)
                console.print(format_commit(commit, is_new))
    
    return total_commits

def search_adjacent_dates(repos, search_date, author, stats, verbose=False):
    """Search adjacent dates until commits are found or user cancels."""
    all_results = defaultdict(list)
    days_to_expand = 1
    total_commits = 0
    previous_total = 0
    today = datetime.now().date()
    seen_commits = set()  # Track seen commits to highlight new ones
    
    # Initial search just for the specified date
    try:
        results, commits_found, _ = search_date_range(
            repos, search_date, author, is_adjacent=False, stats=stats, verbose=verbose
        )
        all_results.update(results)
        total_commits = display_commits_by_date(all_results, seen_commits)
        
        if total_commits == 0:
            console.print(f"\n[yellow]No commits found.[/]")
        
        while True:
            previous_total = total_commits
            
            prompt = f"Expand search to ±{days_to_expand} day [dim](Y/n)[/]"
            response = Prompt.ask(prompt, default="y", show_default=False).lower()
            if response != "y":  # Only continue if exactly "y"
                break
            
            console.print(f"\nSearching ±{days_to_expand} day...")
            
            # Search one day before and after (if not in future)
            before_date = search_date.date() - timedelta(days=days_to_expand)
            after_date = search_date.date() + timedelta(days=days_to_expand)
            
            # Only search future dates up to today
            if after_date > today:
                after_date = today
            
            # Search the entire range from before_date to after_date
            for current_date in [before_date, after_date]:
                try:
                    results, commits_found, _ = search_date_range(
                        repos, datetime.combine(current_date, datetime.min.time()),
                        author, is_adjacent=True, stats=stats, verbose=verbose
                    )
                    # Update results while preserving existing commits
                    for repo, commits in results.items():
                        all_results[repo].extend(c for c in commits if c.hexsha not in seen_commits)
                except SearchCancelled:
                    raise
            
            # Display complete results for the entire range
            if all_results:
                total_commits = display_commits_by_date(all_results, seen_commits)
                if total_commits > previous_total:
                    console.print(f"\n[green]Found {total_commits - previous_total} new commit{'s' if total_commits - previous_total > 1 else ''}[/]")
                else:
                    console.print("\n[bold yellow]No new commits found in this range[/]")
            else:
                console.print("\n[yellow]No commits found in this range.[/]")
            
            days_to_expand += 1
    
    except SearchCancelled:
        if all_results:
            console.print("\n[yellow]Search interrupted.[/]")
            total_commits = display_commits_by_date(all_results, seen_commits)
        raise
    
    return all_results

def search_date_range(repos, date, author, is_adjacent=False, stats=None, verbose=False):
    """Search repositories for commits on a specific date."""
    results = defaultdict(list)
    total_commits = 0
    search_times = []
    
    with Progress(
        TextColumn("[bold blue]{task.description}"),
        BarColumn(bar_width=40),
        TextColumn("[progress.percentage]{task.completed}/{task.total}"),
        TextColumn("•"),
        TimeElapsedColumn(),
        console=console,
        expand=True,
        transient=True
    ) as progress:
        task = progress.add_task(
            f"Searching repositories",
            total=len(repos)
        )
        
        try:
            for repo_path in repos:
                repo_name = Path(repo_path).name
                if verbose:
                    progress.update(task, description=f"Searching {repo_name:<30}")
                else:
                    progress.update(task, description="Searching repositories")
                
                try:
                    with timeout(30):
                        start_time = time.time()
                        result = search_commits_in_repo(repo_path, date, author, verbose=verbose)
                        search_time = time.time() - start_time
                        search_times.append(search_time)
                        
                        if stats:
                            stats.repo_search_times.append(search_time)
                        
                        if result:
                            repo_name, commits = result
                            results[repo_name].extend(commits)
                            total_commits += len(commits)
                            if verbose:
                                console.print(f"[green]✓ Found {len(commits)} commits in {repo_name}[/]")
                except TimeoutError:
                    if verbose:
                        console.print(f"[yellow]Warning: Search timeout for {repo_name}[/]")
                except KeyboardInterrupt:
                    raise SearchCancelled
                
                progress.advance(task)
                
        except KeyboardInterrupt:
            raise SearchCancelled
    
    return results, total_commits, search_times

# Add timeout context manager
class timeout:
    def __init__(self, seconds):
        self.seconds = seconds
    
    def handle_timeout(self, signum, frame):
        raise TimeoutError()
    
    def __enter__(self):
        signal.signal(signal.SIGALRM, self.handle_timeout)
        signal.alarm(self.seconds)
    
    def __exit__(self, type, value, traceback):
        signal.alarm(0)

@click.command()
@click.option('--date', '-d', default=None, help='Date to search (YYYY-MM-DD)')
@click.option('--author', '-a', default=None, help='Author email (required)')
@click.option('--verbose', '-v', is_flag=True, help='Show detailed progress and statistics')
@click.option('--directory', '-D', help='Single directory to search (expands ~ to home directory)')
@click.option('--directories', '-dirs', multiple=True, help='Multiple directories to search (can be specified multiple times)')
def main(date, author, verbose, directory, directories):
    """Search for commits across multiple repositories."""
    if not author:
        console.print("[red]Error: --author/-a option is required[/]")
        return

    stats = SearchStats()
    
    try:
        search_date = datetime.strptime(date, "%Y-%m-%d") if date else datetime.now()
    except ValueError:
        console.print("[red]Error: Invalid date format. Please use YYYY-MM-DD[/]")
        return
    
    try:
        # Handle directory options
        search_dirs = []
        if directory:
            search_dirs = [directory]
        elif directories:
            search_dirs = list(directories)
        else:
            search_dirs = DEFAULT_SEARCH_DIRS
        
        console.print("[bold]Phase 1: Repository Discovery[/]")
        if verbose:
            if directory:
                console.print(f"Searching in directory: {directory}")
            elif directories:
                console.print("Searching in directories:")
                for d in directories:
                    console.print(f"  • {d}")
            else:
                console.print("Searching in default directories:")
                for d in DEFAULT_SEARCH_DIRS:
                    console.print(f"  • {d}")
        
        repos = find_git_repos(base_dirs=search_dirs, stats=stats, verbose=verbose)
        
        if not repos:
            console.print("[red]No Git repositories found.[/]")
            if verbose:
                stats.display()
            return
        
        console.print(f"\n[bold]Phase 2: Commit Search[/]")
        if verbose:
            console.print(f"Searching [bold]{len(repos)}[/] repositories from [bold]{search_date.date()}[/] to present")
        
        try:
            results = search_adjacent_dates(repos, search_date, author, stats=stats, verbose=verbose)
            
            if verbose:
                stats.display()
                        
        except SearchCancelled:
            console.print("\n[yellow]Search cancelled by user[/]")
            if verbose:
                stats.display()
            sys.exit(0)
            
    except KeyboardInterrupt:
        console.print("\n[yellow]Search cancelled by user[/]")
        if verbose:
            stats.display()
        sys.exit(0)

if __name__ == '__main__':
    main() 