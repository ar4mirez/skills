// Android: register in your Application subclass →
//   Hotwire.registerBridgeComponents(BridgeComponentFactory("button", ::ButtonComponent))
import android.util.Log
import dev.hotwire.core.bridge.BridgeComponent
import dev.hotwire.core.bridge.BridgeDelegate
import dev.hotwire.core.bridge.Message
import dev.hotwire.navigation.destinations.HotwireDestination
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

class ButtonComponent(
    name: String,
    private val delegate: BridgeDelegate<HotwireDestination>
) : BridgeComponent<HotwireDestination>(name, delegate) {

    override fun onReceive(message: Message) {
        when (message.event) {
            "connect" -> handleConnectEvent(message)
            else -> Log.w("ButtonComponent", "Unknown event for message: $message")
        }
    }

    private fun handleConnectEvent(message: Message) {
        val data = message.data<MessageData>() ?: return
        // Add a toolbar menu item on delegate.destination titled data.title
        // whose click calls performButtonClick().
    }

    private fun performButtonClick(): Boolean = replyTo("connect")

    @Serializable
    data class MessageData(@SerialName("title") val title: String)
}
