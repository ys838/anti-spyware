from flask import Flask, render_template, request, redirect,jsonify
from phone_scanner import AndroidScan, IosScan, TestScan
import json
import blacklist
import config
import parse_dump
import dataset

FLASK_APP = Flask(__name__)
android = AndroidScan()
ios = IosScan()
test = TestScan()
db = dataset.connect(config.SQL_DB_PATH)



def get_device(k):
    return {
        'android': android,
        'ios': ios,
        'test': test
    }.get(k)


@FLASK_APP.route("/", methods=['GET'])
def index():
    return render_template(
        'index.html',
        devices={
            'Android': android.devices(),
            'iOS': ios.devices(),
            'Test': test.devices()
        }, apps={}
    )


@FLASK_APP.route('/details/app/<device>', methods=['GET'])
def app_details(device):
    sc = get_device(device)
    appid = request.args.get('appId')
    ser = request.args.get('serial')
    d, info = sc.app_details(ser, appid)
    d = d.to_dict(orient='index2').get(0, {})
    d['appId'] = appid
    return render_template(
        'app.html',
        app=d,
        info=info
    )


def first_element_or_none(a):
    if a: return a[0]


def is_success(b, msg_succ="", msg_err=""):
    if b:
        return msg_succ if msg_succ else "Success!", 200
    else:
        return msg_err if msg_err else "Failed", 401

@FLASK_APP.route("/scan/<device>", methods=['GET'])
def scan(device):
    # ser = request.args.get('serial')
    sc = get_device(device)
    ser = first_element_or_none(sc.devices())
    print(">>>scan_device", device, "<<<<<")

    # return json.dumps({
    #     'apps': sc.find_spyapps(serialno=ser).to_json(orient="index"),
    #     'serial': ser,
    #     'error': config.error()
    # })
    apps = sc.find_spyapps(serialno=ser).fillna('')
    # apps['flags'] = apps.flags.apply(blacklist.flag_str)
    return render_template(
        'test.html',
        apps=apps.to_dict(orient='index'),
        sysapps=set(sc.get_system_apps(serialno=ser)),
        serial=ser,
        device=device,
        error=config.error(),
    )

##############  RECORD DATA PART FRONT END (ANMOL)  ###############################
@FLASK_APP.route("/login", methods=["GET", "POST"])
def login():
    if request.method == 'POST':
        print("inside post")
        username = request.json['username']
        password = request.json['password']
        print("username---->" + username)
        print("password---->" + password)
        table_name = "employee"
        curr_table = db.load_table(table_name)
        print(curr_table)
        employee = curr_table.find_one(username=username)
        if(employee):
            emp_username = employee["username"]
            emp_password = employee["password"]
            if(emp_password == password):
                print("access granted")
                return jsonify({'loggedin' : True})
            else:
                return jsonify({'loggedin' : False})
        else:
            return jsonify({'loggedin' : False})



@FLASK_APP.route("/newclient", methods=["GET", "POST"])
def new_client():
    if request.method == 'POST':
        print("inside post")
        name = request.json['name']
        address = request.json['address']
        phone = request.json['phone']
        employee = request.json['employee']
        table_name = "client"
        data = dict(name=name, address=address, phone=phone, employee=employee)
        curr_table = db.get_table(table_name)
        print(curr_table)
        curr_table.insert(data)
        db.commit()
        return jsonify({'created' : True})
    else:
        return jsonify({'created' : False})

# gets all the clients that are managed by a particular employee
@FLASK_APP.route("/getclients", methods=["GET", "POST"])
def get_clients():
    try:
        emp = request.json['employee']
        table_name = "client"
        curr_table = db.load_table(table_name)
        print(curr_table)
        current_clients = curr_table.find(employee=emp)
        for cl in current_clients:
            print(cl)
        return "Success",200
    except Exception as ex:
        print(ex)
        return False



##############  RECORD DATA PART END  ###############################

############## VIEW ROUTING  ###############################
@FLASK_APP.route("/mode", methods=['GET'])
def mode():
    return render_template('mode.html')

@FLASK_APP.route("/disclaimer", methods=['GET'])
def disclaimer():
    return render_template('disclaimer.html')

@FLASK_APP.route("/profile", methods=['GET','POST']) #post?
def profile():
    return render_template('profile.html')

@FLASK_APP.route("/existing", methods=['GET'])
def existing():
    return render_template('db.html')

@FLASK_APP.route("/confirm", methods=['GET'])
def confirm():
    return render_template('confirm.html')

@FLASK_APP.route("/scan", methods=['GET'])
def index2():
    return render_template(
        'main.html',
        devices={
            'Android': android.devices(),
            'iOS': ios.devices(),
            'Test': test.devices()
        }, apps={}
    )

##############  VIEW ROUTING END  ###############################

@FLASK_APP.route("/delete/app/<device>", methods=["POST"])
def delete_app(device):
    sc = get_device(device)
    serial = request.form.get('serial')
    appid = request.form.get('appid')
    # TODO: Record the uninstall and note
    r = sc.uninstall(serialno=serial, appid=appid)
    r &= sc.save('app_uninstall', serial=serial, appid=appid, notes=request.form.get('note', ''))
    return is_success(r, "Success!", config.error())

@FLASK_APP.route('/save/appnote/<device>', methods=["POST"])
def save_app_note(device):
    sc = get_device(device)
    serial = request.form.get('serial')
    appId = request.form.get('appId')
    note = request.form.get('note')
    return is_success(sc.save('notes', serialno=serial, appId=appId, note=note))


@FLASK_APP.route('/save/metainfo/<device>', methods=["POST"])
def record_response(device):
    print("device----->" + device)
    sc = get_device(device)
    print(sc)
    r = bool(sc.save(
        'response',
        response=json.dumps(request.form),
        serial=request.form.get('serial'),
    ))
    return is_success(r, "Success!", "Could not save for some reason. See logs in the terminal.")


if __name__ == "__main__":
    FLASK_APP.run(debug=config.DEBUG)
