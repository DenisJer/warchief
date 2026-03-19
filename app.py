from flask import Flask, request, jsonify

app = Flask(__name__)


@app.route("/hello", methods=["GET"])
def hello():
    return jsonify({"message": "Hello, World!"})


@app.route("/echo", methods=["POST"])
def echo():
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Invalid or missing JSON body"}), 400
    return jsonify(data)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
