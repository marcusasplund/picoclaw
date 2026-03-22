package heartbeat

func PollSMS(ctx context.Context, client *smsgateway.Client) {
	msgs, err := client.FetchUnread(ctx)
	if err != nil {
		// logga
		return
	}

	for _, m := range msgs {
	
		handleIncomingSMS(m)

		// delete först efter success
		client.Delete(ctx, m.Index)
	}
}
