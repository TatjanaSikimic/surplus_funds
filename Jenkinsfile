pipeline {
    agent any

    environment {
        DATABASE_URL = 'postgresql+psycopg://postgres:postgres@db:5432/surplus_funds'
        REQUIRE_DB   = '1'
    }

    stages {
        stage('Setup') {
            steps {
                sh '''
                    python3 -m venv .venv
                    .venv/bin/pip install --upgrade pip
                    .venv/bin/pip install -e ".[dev]"
                    mkdir -p reports
                '''
            }
        }

        stage('Lint (PEP 8)') {
            steps {
                sh '.venv/bin/ruff check .'
                sh '.venv/bin/ruff format --check .'
            }
        }

        stage('Migrations') {
            steps {
                sh '.venv/bin/alembic downgrade base'
                sh '.venv/bin/alembic upgrade head'
            }
        }

        stage('Tests') {
            steps {
                sh '''
                    .venv/bin/pytest \
                        --junitxml=reports/junit.xml \
                        --cov=surplus_funds \
                        --cov-report=term \
                        --cov-report=html:reports/htmlcov
                '''
            }
        }

        stage('Smoke test CLI') {
            steps {
                sh '''
                    .venv/bin/surplus-funds sources
                    .venv/bin/surplus-funds scrape ga_hall --file Website-Excess-Funds-List-09-29-2023.pdf
                    .venv/bin/surplus-funds funds --state GA --limit 5
                    .venv/bin/surplus-funds stale ga_hall

                    # Excel/CSV are archived as artifacts, the HTML page is published as a report.
                    mkdir -p reports/exports
                    .venv/bin/surplus-funds export reports/exports/surplus_funds.xlsx
                    .venv/bin/surplus-funds export reports/exports/surplus_funds.csv
                    .venv/bin/surplus-funds export reports/exports/surplus_funds.html
                    test -s reports/exports/surplus_funds.xlsx
                    test "$(wc -l < reports/exports/surplus_funds.csv)" -gt 1
                    grep -q "<td" reports/exports/surplus_funds.html
                '''
            }
        }

        stage('Dependency audit') {
            steps {
                catchError(buildResult: 'UNSTABLE', stageResult: 'UNSTABLE') {
                    sh '.venv/bin/pip-audit --skip-editable'
                }
            }
        }
    }

    post {
        always {
            junit allowEmptyResults: true, testResults: 'reports/junit.xml'
            // Only files meant for download; HTML reports are published below.
            archiveArtifacts artifacts: 'reports/exports/*.xlsx, reports/exports/*.csv, reports/junit.xml',
                             allowEmptyArchive: true
            // Requires the HTML Publisher plugin. Each report gets a link on the build page.
            publishHTML(target: [
                reportName: 'Coverage Report',
                reportDir: 'reports/htmlcov',
                reportFiles: 'index.html',
                keepAll: true,
                alwaysLinkToLastBuild: true,
                allowMissing: true,
            ])
            publishHTML(target: [
                reportName: 'Surplus Funds',
                reportDir: 'reports/exports',
                reportFiles: 'surplus_funds.html',
                keepAll: true,
                alwaysLinkToLastBuild: true,
                allowMissing: true,
            ])
        }
    }
}
