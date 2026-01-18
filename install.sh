BASEDIR=$(dirname "$0")

kubectl create namespace spark
kubectl apply -f $BASEDIR/driver-proxy.yaml -n spark
kubectl apply -f $BASEDIR/spark-rbac.yaml -n spark

helm repo add kyverno https://kyverno.github.io/kyverno/
helm repo update
kubectl create namespace kyverno
helm install kyverno kyverno/kyverno -n kyverno
helm install kyverno-policies kyverno/kyverno-policies -n kyverno

helm repo add policy-reporter https://kyverno.github.io/policy-reporter
helm repo update
helm install policy-reporter policy-reporter/policy-reporter -n kyverno --set ui.enabled=true --set kyverno-plugin.enabled=true
kubectl port-forward service/policy-reporter-ui 8082:8080 -n kyverno