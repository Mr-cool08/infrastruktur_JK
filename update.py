import subprocess



def update():
    subprocess.run(["git", "pull"], check=True)
    subprocess.run(["docker", "compose", "pull"], check=True)
    subprocess.run(["docker", "compose", "down"], check=True)
    subprocess.run(["docker", "compose", "up", "-d", "--force-recreate", "--remove-orphans"], check=True)
    print("Update completed successfully.")