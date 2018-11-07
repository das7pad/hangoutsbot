"""Generate the declarative Jenkins pipeline"""

__author__ = 'Jakob Ackermann <das7pad@outlook.com>'

import pathlib


VERSIONS = [
    '3.5.3',
    '3.5.4',
    '3.5.5',
    '3.5.6',

    '3.6.0',
    '3.6.1',
    '3.6.2',
    '3.6.3',
    '3.6.4',
    '3.6.5',
    '3.6.6',
    '3.6.7',

    '3.7.0',
]

PIPELINE = """
//
// This file is autogenerated.
// To update, run:
//
//    make Jenkinsfile
//

pipeline {
    agent none
    environment {
        GIT_COMMITTER_NAME  = 'Joe Doe'
        GIT_COMMITTER_EMAIL = 'joe.doe@example.com'
        HOME                = '/tmp/'
    }
    options {
        timestamps()
    }
    stages {
        stage('Parallel Stage') {
            parallel {
%(stages)s
            }
        }
    }
}
"""

STAGE = """
                stage('Python:%(version)s') {
                    agent {
                        docker {
                            image 'python:%(version)s'
                        }
                    }
                    stages {
                        stage('Python:%(version)s Checkout') {
                            steps {
                                checkout scm
                            }
                        }
                        stage('Python:%(version)s Install') {
                            steps {
                                sh 'make install'
                            }
                        }
                        stage('Python:%(version)s Test') {
                            steps {
                                sh 'make test'
                            }
                        }
                    }
                }
"""


def main():
    jenkinsfile = pathlib.Path(__file__).parent.parent / 'Jenkinsfile'

    stages = '\n'.join(
        STAGE.strip('\n') % dict(version=version)
        for version in VERSIONS
    )

    pipeline = PIPELINE.lstrip('\n') % dict(stages=stages)
    jenkinsfile.write_text(pipeline)


if __name__ == '__main__':
    main()
