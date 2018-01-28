def python_versions = [
    "3.5.0", "3.5.1", "3.5.2", "3.5.3", "3.5.4",
    "3.6.0", "3.6.1", "3.6.2", "3.6.3", "3.6.4",
]

def steps = python_versions.collectEntries {
    ["Python $it": run_ci(it)]
}

parallel steps

def custom_env = [
    'GIT_COMMITTER_NAME="Joe Doe"',
    'GIT_COMMITTER_EMAIL="joe.doe@example.com"',
]

def run_ci(python_version) {
    return {
        withEnv(custom_env) {
            docker.image("python:${python_version}").inside {
                checkout scm
                sh 'make venv-dev'
                sh 'make install'
                sh 'make test'
            }
        }
    }
}
