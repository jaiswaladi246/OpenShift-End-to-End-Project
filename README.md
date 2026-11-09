# OpenShift End-to-End Project — DevOps Shack

We take a real 3-tier application and run it on **Red Hat OpenShift** the way companies do: OpenShift builds the images straight from Git, deploys them, connects the tiers, exposes the app on a secure URL, and rebuilds automatically when the code changes.

**The app — DevOps Shack Command Center**, a team sprint board with a live platform view:

- **Sprint Board:** drag-and-drop tasks across To do / In progress / Review / Done, priorities, search and filters
- **Dashboard:** animated KPIs, status donut and priority bars, all from the database
- **Platform & Chaos Lab:** which pod answered each request, traffic split across pods, plus buttons that burn CPU, fail the readiness probe or crash a pod, so you can watch OpenShift react
- **Activity:** a timeline of every change

| Tier | Technology | How OpenShift builds it |
|---|---|---|
| Frontend | HTML/JS served by nginx (`frontend/`) | Source-to-Image with the nginx builder |
| Backend | Python Flask API with gunicorn (`backend/`) | Source-to-Image with the Python builder |
| Database | PostgreSQL 15 with persistent storage | Ready-made image (`quay.io/sclorg/postgresql-15-c9s`) |

```
Browser ──HTTPS──▶ Route ──▶ frontend (nginx) ──/api──▶ backend (Python, 2 pods) ──▶ postgresql (PVC)
```

The Platform tab shows which backend pod answered each request. Scale the backend and watch the traffic spread.

**Backend settings (environment variables):** `DB_HOST`, `DB_USER`, `DB_PASSWORD`, `DB_NAME` (from the `shackboard-db` Secret), `APP_VERSION`, `APP_ENV`, `CHAOS_ENABLED` (`true` turns on the Chaos Lab; leave it off anywhere real), and `POD_NAMESPACE` / `NODE_NAME` from the downward API.

---

## 1. OpenShift vs Kubernetes, in plain words

OpenShift **is** Kubernetes, with everything a company would otherwise bolt on by itself already installed, integrated and supported by Red Hat.

| Topic | Plain Kubernetes | OpenShift |
|---|---|---|
| Building images | You write a Dockerfile and run a CI job | **Source-to-Image (S2I)**: point at a Git repo, OpenShift builds the image |
| Exposing an app | Install an Ingress controller, then write Ingress objects | **Routes** are built in, with HTTPS out of the box |
| Security | Containers can run as root unless you stop them | Containers run as a **random non-root user** by default (Security Context Constraints) |
| Image storage | Bring your own registry | **Built-in registry and ImageStreams**; a new image can trigger a redeploy automatically |
| Web UI | Optional dashboard | Full **web console** with Developer and Administrator views and a Topology map |
| Namespaces | Namespaces | **Projects**: namespaces with extra access control and quotas |
| CLI | `kubectl` | `oc` (does everything `kubectl` does, plus OpenShift features) |
| CI/CD | Install it yourself | **OpenShift Pipelines** (Tekton) and **OpenShift GitOps** (Argo CD) available as operators |
| Support | Community | Supported by Red Hat, with a certified ecosystem |

**Where companies use it:** banks, telecoms, insurance and government teams, wherever security rules and vendor support matter.

---

## 2. Getting OpenShift at no cost

| Option | Cost | What you get | Best for |
|---|---|---|---|
| **Developer Sandbox** (used in this project) | Free for 30 days, renewable | A project on a real, shared OpenShift cluster run by Red Hat, with web console and terminal | Learning and demos, nothing to install |
| **OpenShift Local** (formerly CRC) | Free with a Red Hat account | A single-node OpenShift on your own laptop | Practising cluster-admin tasks offline |

OpenShift Local needs 4 physical CPU cores, about 9 GB of free RAM and 35 GB of disk, and **does not support nested virtualization**, so it won't run on a normal EC2 instance (only on costly bare-metal types) or inside VirtualBox. On Windows it needs Pro or Enterprise (not Home).

**Sign up for the Sandbox:** go to https://sandbox.redhat.com, log in with a Red Hat account, verify your phone number, and click **Try it** under OpenShift.

---

## 3. Deploy with the web console (no YAML)

This is the path we show first in the video.

1. **Database:** *+Add → Container images*, image `quay.io/sclorg/postgresql-15-c9s:latest`, name `postgresql`, and add environment variables `POSTGRESQL_USER`, `POSTGRESQL_PASSWORD`, `POSTGRESQL_DATABASE` (better: from a Secret, see section 4).
2. **Backend:** *+Add → Import from Git*, repo URL, *Show advanced Git options → Context dir* `/backend`, builder **Python** (version 3.12-ubi9), name `backend`, untick *Create a route*. Add the `DB_*` environment variables.
3. **Frontend:** *+Add → Import from Git*, same repo, context dir `/frontend`, builder **Nginx** (version 1.24-ubi9), name `frontend`, keep *Create a route* ticked.
4. Open **Topology**, watch the builds run, then click the frontend's route icon.

> **Private repo?** In step 2 choose *Source secret → Create new secret* and paste a GitHub **fine-grained token** limited to this one repository with **Contents: Read-only** (Metadata: Read-only is added automatically). OpenShift uses it only to clone.

---

## 4. Deploy with the CLI (`oc`)

Use the **Web Terminal** (the `>_` icon at the top of the console) or install `oc` locally and copy the login command from *your name → Copy login command*.

```bash
git clone https://github.com/jaiswaladi246/openshift-end-to-end-project.git
cd openshift-end-to-end-project

# 1) Database credentials as a Secret (never commit passwords)
oc create secret generic shackboard-db \
  --from-literal=database-user=shackboard \
  --from-literal=database-password=$(openssl rand -hex 12) \
  --from-literal=database-name=shackboard

# 2) Database, backend, frontend
oc apply -f openshift/01-database.yaml
oc apply -f openshift/02-backend.yaml
oc apply -f openshift/03-frontend.yaml

# 3) Watch the builds and pods
oc get builds -w          # Ctrl+C when both show Complete
oc get pods
oc get route shackboard -o jsonpath='https://{.spec.host}{"\n"}'
```

This repo is **private**, so both BuildConfigs clone with the `github-token` source secret. Create it **before step 2** (or in the console: *Secrets → Create → Source secret*, Basic authentication). Type the token at the prompt so it never lands in your shell history:

```bash
read -s -p "GitHub token: " GH_TOKEN; echo
oc create secret generic github-token --type=kubernetes.io/basic-auth \
  --from-literal=username=<github-user> --from-literal=password="$GH_TOKEN"
unset GH_TOKEN
```

For a public fork, delete the `sourceSecret` line from both BuildConfigs instead.


### 4b. Deploy with `oc new-app` (no YAML)

The same app built with imperative commands, the CLI twin of the console's *Container images* and *Import from Git* forms. Run it in the Web Terminal (`>_` icon). It assumes the `github-token` source secret already exists.

```bash
# Secrets whose key names match the variables each app reads
DB_PASSWORD=$(openssl rand -hex 12)
oc create secret generic postgresql-env --from-literal=POSTGRESQL_USER=shackboard \
  --from-literal=POSTGRESQL_PASSWORD=$DB_PASSWORD --from-literal=POSTGRESQL_DATABASE=shackboard
oc create secret generic backend-db --from-literal=DB_USER=shackboard \
  --from-literal=DB_PASSWORD=$DB_PASSWORD --from-literal=DB_NAME=shackboard

# Database: image + settings + Recreate strategy + 1Gi volume
oc new-app quay.io/sclorg/postgresql-15-c9s:latest --name=postgresql -l app.kubernetes.io/part-of=shackboard
oc set env deploy/postgresql --from=secret/postgresql-env
oc patch deploy/postgresql -p '{"spec":{"strategy":{"type":"Recreate","rollingUpdate":null}}}'
oc set volume deploy/postgresql --add --name=postgresql-data --type=pvc \
  --claim-name=postgresql-data --claim-size=1Gi --mount-path=/var/lib/pgsql/data

# Backend: S2I build from the private repo
REPO=https://github.com/jaiswaladi246/openshift-end-to-end-project.git#main
oc new-app python:3.12-ubi9~$REPO --context-dir=backend --source-secret=github-token \
  --name=backend -l app.kubernetes.io/part-of=shackboard
oc set env deploy/backend --from=secret/backend-db
oc set env deploy/backend DB_HOST=postgresql APP_VERSION=v2 APP_ENV=dev CHAOS_ENABLED=true
oc set probe deploy/backend --readiness --get-url=http://:8080/readyz --period-seconds=5
oc set probe deploy/backend --liveness --get-url=http://:8080/healthz --initial-delay-seconds=20
oc scale deploy/backend --replicas=2

# Frontend + public HTTPS route
oc new-app nginx:1.24-ubi9~$REPO --context-dir=frontend --source-secret=github-token \
  --name=frontend -l app.kubernetes.io/part-of=shackboard
oc create route edge shackboard --service=frontend --port=8080-tcp --insecure-policy=Redirect

# Check
oc rollout status deploy/backend && oc get pods -l app.kubernetes.io/part-of=shackboard
curl -s https://$(oc get route shackboard -o jsonpath='{.spec.host}')/api/info; echo
```

Clean up this variant with `oc delete all -l app.kubernetes.io/part-of=shackboard && oc delete pvc postgresql-data`. Never run `oc delete all` without a label: the Web Terminal itself runs as a pod in your project.

---

## 5. The production moments to show

| Moment | Command / action | What it proves |
|---|---|---|
| **Scale** | `oc scale deploy/backend --replicas=3` | The footer's pod name changes as requests are load-balanced |
| **Self-healing** | `oc delete pod -l name=backend` | New pods appear in seconds, the app never goes down |
| **Readiness** | `oc scale deploy/postgresql --replicas=0` | Backend pods turn *not ready* (red ring in Topology) instead of serving errors; scale back to 1 and they recover |
| **Rebuild on change** | Edit `APP_VERSION` or code, then `oc start-build backend --follow` | S2I builds a new image, the ImageStream updates and the Deployment rolls out automatically |
| **Git push → deploy** | `oc describe bc/backend` shows the GitHub webhook URL; add it in the repo's *Settings → Webhooks* with the secret `backend-webhook` | Every push to GitHub triggers a build and deploy |
| **Security by default** | `oc rsh deploy/backend id` | The container runs as a random UID, not root |
| **Chaos: CPU spike** | Chaos Lab → *Burn CPU* | The pod's CPU graph climbs under *Observe*; other pods keep serving |
| **Chaos: readiness** | Chaos Lab → *Fail readiness* | The pod stays Running but leaves the Service endpoints (`oc get endpoints backend`); traffic shifts to healthy pods, then it returns |
| **Chaos: crash** | Chaos Lab → *Crash a pod* | The restart count goes up by one and the pod is back in seconds |
| **Rollback** | `oc rollout undo deploy/backend` | Back to the previous version in one command |

To create the webhook secret: `oc create secret generic backend-webhook --from-literal=WebHookSecretKey=$(openssl rand -hex 16)`.

---

## 6. Clean up

```bash
oc delete all,pvc,secret,imagestream,buildconfig,route -l app=shackboard
oc delete secret shackboard-db
```

---

## 7. Interview questions on this project

- What is the difference between OpenShift and Kubernetes? Name three things OpenShift adds.
- What is Source-to-Image, and when would you still use a Dockerfile?
- What is a Route, and how is it different from an Ingress?
- Why does OpenShift run containers as a random UID, and what breaks when an image expects root?
- What is an ImageStream, and how does it trigger a redeploy?
- Readiness vs liveness probe: what happens to traffic when each one fails?

---

**DevOps Shack** · YouTube: [DevOps Shack](https://www.youtube.com/@devopsshack) · Learn this hands-on in the DevSecOps + Cloud + AI bootcamp (Batch 16) at [devopsshack.com](https://devopsshack.com)
