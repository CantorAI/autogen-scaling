import cantor thru 'lrpc:1000'

@cantor.Task(AUTOGEN=1)
def autogen_task():
	p_id = pid()
	cantor.log("in autogen_task pid=${p_id}")
	return True


await cantor.OnShutdown
