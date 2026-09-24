// iOS: register in AppDelegate → Hotwire.registerBridgeComponents([ButtonComponent.self])
import HotwireNative
import UIKit

final class ButtonComponent: BridgeComponent {
    override class var name: String { "button" }

    override func onReceive(message: Message) {
        guard let viewController else { return }
        addButton(via: message, to: viewController)
    }

    private var viewController: UIViewController? {
        delegate?.destination as? UIViewController
    }

    private func addButton(via message: Message, to viewController: UIViewController) {
        guard let data: MessageData = message.data() else { return }

        let action = UIAction { [unowned self] _ in
            self.reply(to: "connect")
        }
        viewController.navigationItem.rightBarButtonItem = UIBarButtonItem(title: data.title, primaryAction: action)
    }
}

private extension ButtonComponent {
    struct MessageData: Decodable {
        let title: String
    }
}
