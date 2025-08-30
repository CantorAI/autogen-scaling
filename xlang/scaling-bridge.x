import cantor thru 'lrpc:1000'

def Test(info):
	cantor.log(info)


@cantor.Task(AUTOGEN=1)
def autogen_task(dataFrame):
	p_id = pid()
	pyObj = py_deserialize(dataFrame)
	task_spec = pyObj["task_spec"]
	qualname =  task_spec.qualname
	cantor.log("in autogen_task pid=${p_id},qualname=${qualname}")
	return True

def RunTask(dataFrame):
	retVal = autogen_task.run(dataFrame)
	return retVal