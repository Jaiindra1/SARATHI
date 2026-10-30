import re
from uuid import uuid4

from flask import Flask, render_template, request, jsonify, redirect, url_for

from services.search_jobs import search_jobs, SearchBusy, RequestConflict
from services.feedback_service import send_feedback_email


app = Flask(__name__, template_folder="templates")


FEEDBACK_CATEGORIES = [
    "Bug report",
    "Feature suggestion",
    "User experience",
    "Product search issue",
    "Other",
]


def is_valid_email(email):
    if not email or len(email) > 254:
        return False

    if "\r" in email or "\n" in email:
        return False

    return re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email) is not None


def validated_query(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Please enter a product name.")
    if len(value.strip()) > 200:
        raise ValueError("Please keep the product name to 200 characters or fewer.")
    return value.strip()


@app.route("/", methods=["GET", "POST"])
def home():
    query, products, message = "", [], ""
    job_id = request.args.get("job", "") if request.method == "GET" else ""
    status_code = 200
    if request.method == "POST":
        try:
            query = validated_query(request.form.get("query"))
            submission = search_jobs.submit(query, request.form.get("request_id", uuid4().hex))
            job_id = submission["job_id"]
            return redirect(url_for("home", job=job_id), code=303)
        except ValueError as error:
            message, status_code = str(error), 400
        except (SearchBusy, RequestConflict) as error:
            message, status_code = str(error), 409
        except Exception:
            app.logger.exception("Unable to submit product search")
            message, status_code = "Unable to start search. Please try again later.", 503
    if job_id:
        job = search_jobs.get(job_id, include_products=True)
        if job is None:
            message = "This search is unavailable. The service may have restarted or the search expired. Please search again."
            job_id = ""
        else:
            query, message = job["query"], job["message"]
            if job["status"] in {"completed", "failed"}:
                products = job["products"]
                warning = job.get("persistence", {}).get("warning")
                if warning:
                    message = f"{message} {warning}"
    return render_template("index.html", query=query, products=products,
                           message=message, job_id=job_id), status_code


@app.route("/api/search", methods=["POST"])
def api_search():
    data = request.get_json(silent=True)
    try:
        query = validated_query(data.get("query") if isinstance(data, dict) else None)
        submission = search_jobs.submit(query, data.get("request_id"))
        job_id = submission["job_id"]
    except ValueError as error:
        return jsonify(success=False, message=str(error), products=[]), 400
    except (SearchBusy, RequestConflict) as error:
        return jsonify(success=False, message=str(error), products=[]), 409
    except Exception:
        app.logger.exception("Unable to submit product search")
        return jsonify(success=False, message="Unable to start search. Please try again later.", products=[]), 503
    return jsonify(success=True, job_id=job_id, status=submission["status"],
                   status_url=url_for("job_status", job_id=job_id),
                   results_url=url_for("job_results", job_id=job_id)), 202


def job_response(job_id, include_products=False):
    job = search_jobs.get(job_id, include_products=include_products)
    if job is None:
        response = jsonify(success=False, message="This search is unavailable. The service may have restarted or the search expired. Please search again.")
        response.status_code = 404
    else:
        response = jsonify(success=job["status"] != "failed", **job)
        if include_products and job["status"] in {"queued", "running"}:
            response.status_code = 202
    response.headers["Cache-Control"] = "no-store"
    return response


@app.route("/api/search/<job_id>/status")
def job_status(job_id):
    return job_response(job_id)


@app.route("/api/search/<job_id>/results")
def job_results(job_id):
    return job_response(job_id, include_products=True)


@app.route("/feedback", methods=["GET", "POST"])
def feedback():

    form = {}

    if request.method == "GET":
        return render_template(
            "feedback.html",
            message="",
            form=form,
            categories=FEEDBACK_CATEGORIES,
        )

    form = {
        "name": request.form.get("name", "").strip(),
        "email": request.form.get("email", "").strip(),
        "category": request.form.get("category", "").strip(),
        "rating": request.form.get("rating", "").strip(),
        "feature": request.form.get("feature", "").strip(),
        "subject": request.form.get("subject", "").strip(),
        "message": request.form.get("message", "").strip(),
    }

    if request.form.get("website", "").strip():
        return render_template(
            "feedback.html",
            message="Unable to process this submission.",
            form={},
            categories=FEEDBACK_CATEGORIES,
        )

    if not all([
        form["name"],
        form["email"],
        form["category"],
        form["subject"],
        form["message"],
    ]):
        error_message = "Please complete all required fields."

    elif (
        len(form["name"]) > 80
        or len(form["email"]) > 254
        or len(form["subject"]) > 120
        or len(form["feature"]) > 100
        or len(form["message"]) > 3000
    ):
        error_message = "One or more fields exceed the allowed length."

    elif not is_valid_email(form["email"]):
        error_message = "Please enter a valid email address."

    elif form["category"] not in FEEDBACK_CATEGORIES:
        error_message = "Please select a valid feedback category."

    elif form["rating"] and form["rating"] not in ["1", "2", "3", "4", "5"]:
        error_message = "Please select a valid rating."

    else:
        error_message = ""

    if error_message:
        return render_template(
            "feedback.html",
            message=error_message,
            form=form,
            categories=FEEDBACK_CATEGORIES,
        )

    form["rating"] = int(form["rating"]) if form["rating"] else None

    try:
        send_feedback_email(form)

        return render_template(
            "feedback.html",
            message="Thank you! Your feedback has been submitted successfully.",
            form={},
            categories=FEEDBACK_CATEGORIES,
        )

    except Exception:
        app.logger.exception("Feedback email delivery failed")

        return render_template(
            "feedback.html",
            message="We couldn't send your feedback right now. Please try again later.",
            form=form,
            categories=FEEDBACK_CATEGORIES,
        )


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)