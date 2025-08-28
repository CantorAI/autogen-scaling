import cantor thru 'lrpc:1000'

def Test(info):
	cantor.log(info)


@cantor.Task(AUTOGEN=1)
def autogen_task(dataFrame):
	p_id = pid()
	cantor.log("in autogen_task pid=${p_id}")
	return dataFrame

def RunTask(dataFrame):
	retVal = autogen_task.run(dataFrame)
	return retVal